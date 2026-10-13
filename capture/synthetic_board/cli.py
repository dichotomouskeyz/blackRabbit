"""Standalone APEX biosignal LSL stream simulator."""

import argparse
import signal

from capture.logger import get_logger, set_session_id
from capture.synthetic_board.outlets import (
    build_stream_specs,
    create_outlets,
    validate_specs,
)
from capture.synthetic_board.runtime import (
    build_threads,
    clear_stop_event,
    handle_stop,
    run_until_stopped,
)
from config import settings

log = get_logger("synthetic_board")
set_session_id(None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="APEX biosignal LSL stream simulator")
    parser.add_argument(
        "--eeg-rate",
        type=float,
        default=float(settings.SAMPLE_RATE_EEG),
        help=f"EEG samples per second (default: {settings.SAMPLE_RATE_EEG})",
    )
    parser.add_argument(
        "--hrv-rate",
        type=float,
        default=float(settings.SAMPLE_RATE_HRV),
        help=f"HRV samples per second (default: {settings.SAMPLE_RATE_HRV})",
    )
    parser.add_argument(
        "--eda-rate",
        type=float,
        default=float(settings.SAMPLE_RATE_EDA),
        help=f"EDA samples per second (default: {settings.SAMPLE_RATE_EDA})",
    )
    parser.add_argument(
        "--respiration-rate",
        type=float,
        default=float(settings.SAMPLE_RATE_RESPIRATION),
        help=f"Respiration samples per second (default: {settings.SAMPLE_RATE_RESPIRATION})",
    )
    return parser.parse_args()


def main() -> None:
    import pylsl

    settings.validate()
    args = parse_args()
    clear_stop_event()

    specs = build_stream_specs(args)
    validate_specs(specs)

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    outlets = create_outlets(pylsl, specs)

    log.info(
        "synthetic board starting",
        extra={
            "streams": list(outlets),
            "rates_hz": {spec.stream_type: spec.rate_hz for spec in specs},
            "eeg_channels": settings.EEG_CHANNEL_COUNT,
        },
    )

    run_until_stopped(build_threads(pylsl, specs, outlets))
    log.info("synthetic board stopped")
