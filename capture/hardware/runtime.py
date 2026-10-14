"""One coordinator owns acquisition and teardown for every configured source."""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pylsl

from capture.hardware.adapter import Adapter, BrainFlowAdapter, validate_config
from capture.hardware.clock import EpochClock
from capture.hardware.configuration import BridgeConfig
from capture.hardware.errors import HardwareError
from capture.hardware.profiles import finite_number
from capture.hardware.publisher import LSLPublisher
from capture.logger import get_logger
from config import settings


class _Cancelled(Exception):
    pass


def run_bridge(
    config: BridgeConfig,
    *,
    stop_event: threading.Event | None = None,
    duration_s: float | None = None,
    on_event: Callable[[dict], None] | None = None,
    adapter_factory=BrainFlowAdapter,
    publisher_factory=LSLPublisher,
) -> dict[str, Any]:
    """Blocking local runner; another thread may request cancellation via stop_event."""
    settings.validate_hardware()
    validate_config(config)
    if duration_s is not None:
        finite_number(duration_s, "duration_s", positive=True)
    stop = stop_event if stop_event is not None else threading.Event()
    log = get_logger("hardware_bridge")
    run_id = uuid.uuid4().hex
    adapters: list[Adapter] = []
    publishers: list[LSLPublisher] = []
    failure: BaseException | None = None
    cancelled = False
    cleanup_errors: list[str] = []

    def emit(state: str, **fields) -> None:
        event = {"schema_version": 1, "event": state, "run_id": run_id, **fields}
        log.info("Hardware bridge lifecycle", extra=event)
        if on_event is not None:
            on_event(event)

    def check_cancel() -> None:
        if stop.is_set():
            raise _Cancelled()

    try:
        emit("preparing")
        for binding in config.bindings:
            check_cancel()
            adapter = adapter_factory(binding, settings.HARDWARE_BUFFER_SECONDS)
            adapters.append(adapter)
            adapter.prepare()
        check_cancel()
        clock = EpochClock.measure(pylsl.local_clock, settings.HARDWARE_CLOCK_JUMP_SECONDS)
        for binding in config.bindings:
            check_cancel()
            publisher = publisher_factory(binding, clock, run_id, settings.HARDWARE_BUFFER_SECONDS)
            publishers.append(publisher)
            publisher.open()
        for adapter in adapters:
            check_cancel()
            adapter.start()
        started = time.monotonic()
        last_data = {
            (binding.source_id, p.preset): started
            for binding in config.bindings
            for p in binding.profile.presets
        }
        emit("streaming", sources=[b.source_id for b in config.bindings])
        while not stop.is_set():
            if duration_s is not None and time.monotonic() - started >= duration_s:
                break
            clock.check()
            for binding, adapter, publisher in zip(config.bindings, adapters, publishers):
                check_cancel()
                for batch in adapter.read():
                    publisher.publish(batch)
                    if batch.data.ndim == 2 and batch.data.shape[1]:
                        last_data[(binding.source_id, batch.preset)] = time.monotonic()
            if any(
                time.monotonic() - seen > settings.HARDWARE_NO_DATA_SECONDS
                for seen in last_data.values()
            ):
                raise HardwareError("source_timeout", "A configured preset stopped providing data")
            stop.wait(settings.HARDWARE_POLL_SECONDS)
        cancelled = stop.is_set()
    except (_Cancelled, KeyboardInterrupt):
        cancelled = True
        stop.set()
    except Exception as exc:
        # Acquisition boundary: fail the complete group and preserve the original cause.
        failure = exc
        stop.set()
    finally:
        for adapter in reversed(adapters):
            for operation in (adapter.stop, adapter.release):
                try:
                    operation()
                except Exception as exc:
                    cleanup_errors.append(type(exc).__name__)
        for publisher in reversed(publishers):
            try:
                publisher.close()
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__)
        log.info(
            "Hardware bridge resources released",
            extra={
                "event": "resources_released",
                "run_id": run_id,
                "cleanup_errors": cleanup_errors,
            },
        )
    if failure is not None or cleanup_errors:
        code = failure.code if isinstance(failure, HardwareError) else "acquisition_failed"
        if failure is None:
            code = "cleanup_failed"
        log.error(
            "Hardware bridge failed",
            extra={
                "event": "failed",
                "run_id": run_id,
                "error_code": code,
                "error_type": type(failure).__name__ if failure else None,
                "cleanup_errors": cleanup_errors,
            },
        )
        message = str(failure) if isinstance(failure, HardwareError) else "Hardware bridge failed"
        raise HardwareError(code, message) from failure
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "cancelled" if cancelled else "stopped",
        "samples_published": {
            binding.source_id: publisher.sample_counts
            for binding, publisher in zip(config.bindings, publishers)
        },
    }
    emit(result["state"], samples_published=result["samples_published"])
    return result
