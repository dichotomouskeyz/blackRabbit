"""Standalone ECHO marker stream simulator.

Publishes the ECHO Markers LSL stream with a realistic mix of zone
enter/exit events and manual coordinator markers.
Use alongside synthetic_board (biosignals) or real hardware when the
coordinator tablet is absent.

Events published (pipe-delimited, 5 fields each):
    ECHO|zone_enter|<actor_id>|<actor_role>|<zone_label>
    ECHO|zone_exit|<actor_id>|<actor_role>|<zone_label>
    ECHO|manual_marker|<actor_id>|<actor_role>|<marker_label>

Timing:
    Events fire at random intervals drawn uniformly from
    [--min-interval, --max-interval] (seconds). Defaults: 30 – 120 s.

Usage:
    python -m capture.marker_simulator
    python -m capture.marker_simulator --min-interval 10 --max-interval 30
"""

import argparse
import random
import signal
import threading

from capture.logger import get_logger, set_session_id
from config import settings

log = get_logger("marker_simulator")
set_session_id(None)

_stop = threading.Event()

_DEFAULT_MIN_S = 30.0
_DEFAULT_MAX_S = 120.0

# Full emission sequence — exercises all requested event types in a realistic
# order that mimics a therapist and facilitator moving through the session
# space while the coordinator annotates key moments.
_EMISSION_SEQUENCE = (
    # (event_type, actor_id, actor_role, zone_label_or_marker_label)
    ("zone_enter", "therapist_01", "therapist", "in_room"),
    ("zone_enter", "therapist_01", "therapist", "arms_reach"),
    ("manual_marker", "coordinator_01", "coordinator", "dose_administration"),
    ("zone_exit", "therapist_01", "therapist", "arms_reach"),
    ("manual_marker", "coordinator_01", "coordinator", "session_note"),
    ("zone_enter", "facilitator_01", "facilitator", "in_room"),
    ("zone_enter", "facilitator_01", "facilitator", "arms_reach"),
    ("manual_marker", "coordinator_01", "coordinator", "participant_note"),
    ("zone_exit", "facilitator_01", "facilitator", "arms_reach"),
    ("zone_exit", "facilitator_01", "facilitator", "in_room"),
    ("zone_enter", "therapist_01", "therapist", "leaving_room"),
    ("zone_exit", "therapist_01", "therapist", "in_room"),
    ("zone_enter", "therapist_01", "therapist", "out_of_room"),
    ("manual_marker", "coordinator_01", "coordinator", "environmental_note"),
)


def _build_echo_marker(
    actor_id: str,
    actor_role: str,
    zone_label: str,
    event_type: str = "zone_enter",
) -> str:
    return f"ECHO|{event_type}|{actor_id}|{actor_role}|{zone_label}"


EMISSION_SEQUENCE = _EMISSION_SEQUENCE
build_echo_marker = _build_echo_marker


def _handle_stop(signum, frame) -> None:
    _stop.set()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ECHO marker stream simulator")
    p.add_argument(
        "--min-interval",
        type=float,
        default=_DEFAULT_MIN_S,
        help=f"Minimum seconds between events (default: {_DEFAULT_MIN_S})",
    )
    p.add_argument(
        "--max-interval",
        type=float,
        default=_DEFAULT_MAX_S,
        help=f"Maximum seconds between events (default: {_DEFAULT_MAX_S})",
    )
    return p.parse_args()


def main() -> None:
    import pylsl

    settings.validate()
    args = _parse_args()

    if args.min_interval <= 0 or args.max_interval < args.min_interval:
        raise ValueError(f"Invalid interval range: min={args.min_interval} max={args.max_interval}")

    info = pylsl.StreamInfo(
        name=settings.LSL_STREAM_MARKER,
        type="Markers",
        channel_count=1,
        nominal_srate=0,
        channel_format=pylsl.cf_string,
        source_id="untitledplatform_1a_marker_sim",
    )
    outlet = pylsl.StreamOutlet(info)
    log.info(
        "marker simulator starting",
        extra={
            "stream_name": settings.LSL_STREAM_MARKER,
            "min_interval_s": args.min_interval,
            "max_interval_s": args.max_interval,
            "sequence_length": len(_EMISSION_SEQUENCE),
        },
    )

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    event_index = 0
    while not _stop.is_set():
        interval = random.uniform(args.min_interval, args.max_interval)  # nosec B311
        if _stop.wait(interval):
            break

        event_type, actor_id, actor_role, label = _EMISSION_SEQUENCE[
            event_index % len(_EMISSION_SEQUENCE)
        ]
        marker = _build_echo_marker(actor_id, actor_role, label, event_type)
        outlet.push_sample([marker])
        log.info(
            "ECHO marker emitted",
            extra={
                "event_index": event_index,
                "event_type": event_type,
                "actor_id": actor_id,
                "actor_role": actor_role,
                "label": label,
                "interval_s": round(interval, 1),
            },
        )
        event_index += 1

    log.info("marker simulator stopped", extra={"total_events": event_index})


if __name__ == "__main__":
    main()
