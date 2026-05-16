"""Command-line interface for session close."""

import argparse
import sys
from pathlib import Path

from capture.session_close.workflow import run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Close a untitledplatform_1a session and gate post-session batch."
    )
    parser.add_argument("--session-id", required=True, help="Session UUID")
    parser.add_argument(
        "--xdf-path",
        required=True,
        type=Path,
        help="Path to the XDF backup file for this session",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.exit(run(args.session_id, args.xdf_path))
