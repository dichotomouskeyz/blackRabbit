"""Local CLI. stdout is JSON; operational logs remain on stderr."""

import argparse
import asyncio
import json
import signal
import threading

from capture.hardware.adapter import inspect_board, validate_config
from capture.hardware.configuration import load_config
from capture.hardware.discovery import discover
from capture.hardware.errors import HardwareError
from capture.hardware.profiles import load_profile
from capture.hardware.runtime import run_bridge
from config import settings


def _write(data: dict) -> None:
    print(json.dumps(data, allow_nan=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="blackRabbit hardware bridge")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Inspect a BrainFlow board without connecting")
    inspect.add_argument("--board-id", required=True, type=int)
    scan = commands.add_parser("discover", help="Enumerate transport candidates without connecting")
    scan.add_argument("--backend", choices=("usb_serial", "ble"), action="append")
    scan.add_argument("--profile", action="append", default=[])
    for name in ("validate", "run"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True)
        if name == "run":
            command.add_argument("--duration", type=float, help="Stop after this many seconds")
    args = parser.parse_args(argv)
    try:
        settings.validate_hardware()
        if args.command == "inspect":
            _write(inspect_board(args.board_id))
        elif args.command == "discover":
            result = asyncio.run(
                discover(
                    backends=tuple(args.backend or ("usb_serial", "ble")),
                    profiles=tuple(load_profile(p) for p in args.profile),
                )
            )
            _write(result)
            return int(any(b["status"] != "ok" for b in result["backends"]))
        elif args.command == "validate":
            _write(validate_config(load_config(args.config)))
        else:
            stop = threading.Event()
            previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                for sig in previous:
                    signal.signal(sig, lambda _sig, _frame: stop.set())
                run_bridge(
                    load_config(args.config),
                    stop_event=stop,
                    duration_s=args.duration,
                    on_event=_write,
                )
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
        return 0
    except HardwareError as exc:
        _write({"schema_version": 1, "event": "error", "code": exc.code, "message": str(exc)})
        return 1
    except (OSError, RuntimeError) as exc:
        _write(
            {
                "schema_version": 1,
                "event": "error",
                "code": "runtime_error",
                "error_type": type(exc).__name__,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
