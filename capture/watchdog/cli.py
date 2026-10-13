"""Watchdog CLI parsing and forwarder command construction."""

import argparse
import sys
import uuid

from capture.watchdog.models import WatchdogArgs


def parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="untitledplatform_1a process watchdog")
    p.add_argument("--session-id", required=True, type=parse_uuid, help="Session UUID")
    p.add_argument(
        "--participant-id",
        required=True,
        type=parse_uuid,
        help="Pseudonymous participant UUID",
    )
    p.add_argument("--site-id", required=True, type=parse_uuid, help="Site UUID")
    p.add_argument("--sponsor-id", required=True, type=parse_uuid, help="Sponsor UUID")
    return p.parse_args()


def watchdog_args(args: argparse.Namespace) -> WatchdogArgs:
    return WatchdogArgs(
        session_id=args.session_id,
        participant_id=args.participant_id,
        site_id=args.site_id,
        sponsor_id=args.sponsor_id,
    )


def build_forwarder_cmd(args: WatchdogArgs) -> list[str]:
    return [
        sys.executable,
        "-m",
        "capture.lsl_forwarder",
        "--session-id",
        args.session_id,
        "--participant-id",
        args.participant_id,
        "--site-id",
        args.site_id,
        "--sponsor-id",
        args.sponsor_id,
    ]
