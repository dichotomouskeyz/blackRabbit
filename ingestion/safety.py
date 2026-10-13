"""Safety monitor process placeholder for the local simulation harness.

The production safety monitor will evaluate clinical safety rules. For the
1a local harness, this process validates configuration and remains alive so
watchdog/process orchestration can exercise the same lifecycle shape.
"""

import signal
import threading

from capture.logger import get_logger
from config import settings

log = get_logger("safety_monitor")
_stop = threading.Event()


def _handle_stop(signum, frame) -> None:
    _stop.set()


def main() -> None:
    settings.validate()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log.info(
        "safety monitor starting",
        extra={"poll_interval_s": settings.SAFETY_MONITOR_POLL_INTERVAL},
    )
    while not _stop.wait(settings.SAFETY_MONITOR_POLL_INTERVAL):
        log.debug("safety monitor heartbeat")

    log.info("safety monitor stopped")


if __name__ == "__main__":
    main()
