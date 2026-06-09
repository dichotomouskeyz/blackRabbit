"""Forwarder process runtime."""

import signal
import threading
import time

from capture.control import clear_stop_request, stop_requested
from capture.forwarder.models import PAYLOAD_SCHEMA_VERSION, SessionConfig
from capture.forwarder.preflight import load_session_config, verify_session_ready
from capture.forwarder.stream_thread.streams import build_stream_threads
from capture.logger import get_logger, set_session_id
from capture.xdf.writer import XDFWriter
from config import settings

log = get_logger("lsl_forwarder")


def run_forwarder(cfg: SessionConfig) -> None:
    set_session_id(cfg.session_id)
    clear_stop_request(cfg.session_id)
    verify_session_ready(cfg)
    cfg = load_session_config(cfg)

    log.info(
        "forwarder starting",
        extra={
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "simulation_mode": settings.SIMULATION_MODE,
        },
    )

    xdf = XDFWriter(
        session_id=cfg.session_id,
        participant_id=cfg.participant_id,
        site_id=cfg.site_id,
        sponsor_id=cfg.sponsor_id,
    )

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda sig, frame: stop.set())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda sig, frame: stop.set())

    threads = build_stream_threads(cfg, stop, xdf)
    for thread in threads:
        thread.start()

    log.info("all forwarder threads started - press Ctrl+C to stop")
    wait_for_stop(cfg.session_id, stop)

    try:
        join_threads(threads)
    finally:
        xdf.close()
    raise_if_thread_failed(threads)
    log.info("forwarder stopped")


def _join_threads(threads: list[threading.Thread], timeout_s: float = 10.0) -> None:
    for thread in threads:
        thread.join(timeout=timeout_s)
        if thread.is_alive():
            log.error(
                "forwarder thread did not stop after join timeout",
                extra={
                    "thread_name": thread.name,
                    "join_timeout_s": timeout_s,
                },
            )


def _wait_for_stop(session_id: str, stop: threading.Event) -> None:
    try:
        while not stop.is_set():
            if stop_requested(session_id):
                log.info("stop request file detected - flushing buffers")
                stop.set()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutdown requested - flushing buffers")
        stop.set()


def _raise_if_thread_failed(threads: list[threading.Thread]) -> None:
    fatal_threads = [
        thread
        for thread in threads
        if getattr(thread, "fatal_error", None) is not None
    ]
    if not fatal_threads:
        return

    first = fatal_threads[0]
    error = getattr(first, "fatal_error")
    log.critical(
        "forwarder stopped after fatal stream thread error",
        extra={
            "thread_name": first.name,
            "fatal_thread_count": len(fatal_threads),
            "error": str(error),
        },
    )
    raise RuntimeError(f"forwarder failed after fatal stream thread error: {error}") from error


join_threads = _join_threads
wait_for_stop = _wait_for_stop
raise_if_thread_failed = _raise_if_thread_failed
