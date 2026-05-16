"""Signal quality monitor process placeholder for the local simulation harness.

The production SQI monitor will compute modality-specific signal quality
indices. For the 1a local harness, this process validates configuration and
stays alive so the full simulated process graph can be exercised.
"""

import signal
import threading

from capture.logger import get_logger
from config import settings

log = get_logger("sqi_monitor")
_stop = threading.Event()


def _handle_stop(signum, frame) -> None:
    _stop.set()


def main() -> None:
    settings.validate()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log.info(
        "SQI monitor starting",
        extra={"poll_interval_s": settings.SQI_MONITOR_POLL_INTERVAL},
    )
    while not _stop.wait(settings.SQI_MONITOR_POLL_INTERVAL):
        log.debug("SQI monitor heartbeat")

    log.info("SQI monitor stopped")


if __name__ == "__main__":
    main()
