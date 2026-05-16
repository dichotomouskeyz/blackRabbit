"""Thread and signal runtime for the synthetic board."""

import threading
import time
from typing import Any

from capture.logger import get_logger
from capture.synthetic_board.models import StreamSpec

log = get_logger("synthetic_board")

stop_event = threading.Event()


def handle_stop(signum, frame) -> None:
    stop_event.set()


def stream_loop(pylsl, outlet, spec: StreamSpec) -> None:
    interval_s = 1.0 / spec.rate_hz
    next_push = time.monotonic()
    sample_index = 0

    while not stop_event.is_set():
        now = time.monotonic()
        if now < next_push:
            stop_event.wait(min(next_push - now, 0.1))
            continue

        outlet.push_sample(
            spec.sample_factory(sample_index, *spec.factory_args),
            pylsl.local_clock(),
        )
        sample_index += 1
        next_push += interval_s

    log.info(
        "synthetic stream stopped",
        extra={"stream_type": spec.stream_type, "samples_emitted": sample_index},
    )


def build_threads(
    pylsl, specs: list[StreamSpec], outlets: dict[str, Any]
) -> list[threading.Thread]:
    return [
        threading.Thread(
            target=stream_loop,
            name=f"sim_{spec.stream_type.lower()}",
            args=(pylsl, outlets[spec.stream_type], spec),
            daemon=True,
        )
        for spec in specs
    ]


def run_until_stopped(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.start()

    while not stop_event.is_set():
        stop_event.wait(1.0)

    for thread in threads:
        thread.join(timeout=2.0)
