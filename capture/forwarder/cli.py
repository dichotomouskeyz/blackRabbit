"""Command-line interface for the LSL forwarder."""

import argparse
import uuid

from capture.forwarder.models import SessionConfig
from capture.forwarder.runtime import run_forwarder


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="untitledplatform_1a LSL forwarder")
    parser.add_argument("--session-id", required=True, type=_parse_uuid, help="Session UUID")
    parser.add_argument(
        "--participant-id",
        required=True,
        type=_parse_uuid,
        help="Pseudonymous participant UUID",
    )
    parser.add_argument("--site-id", required=True, type=_parse_uuid, help="Site UUID")
    parser.add_argument("--sponsor-id", required=True, type=_parse_uuid, help="Sponsor UUID")
    return parser.parse_args()


def _config_from_args(args: argparse.Namespace) -> SessionConfig:
    return SessionConfig(
        session_id=args.session_id,
        participant_id=args.participant_id,
        site_id=args.site_id,
        sponsor_id=args.sponsor_id,
    )


def main() -> None:
    run_forwarder(_config_from_args(_parse_args()))
