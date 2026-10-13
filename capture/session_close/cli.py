"""Command-line interface for session close."""

import argparse
import sys
from pathlib import Path

from capture.session_close.workflow import run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify and close a blackRabbit capture session.")
    parser.add_argument("--session-id", required=True, help="Session UUID")
    parser.add_argument("--sponsor-id", required=True, help="Sponsor UUID")
    parser.add_argument("--legacy-xdf", action="store_true", help="Read legacy blackRabbit XDF")
    parser.add_argument(
        "--xdf-path",
        required=True,
        type=Path,
        help="Path to the XDF backup file for this session",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.exit(run(args.session_id, args.sponsor_id, args.xdf_path, legacy=args.legacy_xdf))
