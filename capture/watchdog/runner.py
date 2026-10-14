"""Supervise one forwarder and persist its terminal capture state.

Automatic restart is disabled until safe segmented recording is implemented.
An unexpected exit records an alert and marks capture failed. A requested stop
transitions to closing only after the child exits successfully. Closeout is a
separate command, run after the watchdog exits:

    python -m capture.session_close --session-id <sid> --sponsor-id <sponsor> \
        --xdf-path <path>

Database audit triggers record lifecycle changes. Terminal persistence errors
propagate to the caller.
"""

import signal
import sys
import time

from capture.logger import get_logger, set_session_id
from capture.watchdog import models
from capture.watchdog.cli import build_forwarder_cmd, parse_args, watchdog_args
from capture.watchdog.db import log_restart, mark_session_closing, mark_session_failed
from capture.watchdog.process import start_forwarder, stop_forwarder, wait_for_forwarder
from config import settings

log = get_logger("watchdog")


def install_signal_handlers(state: models.WatchdogState, args: models.WatchdogArgs) -> None:
    def _handle_sigterm(signum, frame):
        state.clean_shutdown = True
        process = state.process
        if process and process.poll() is None:
            log.info("SIGTERM received — stopping forwarder")
            stop_forwarder(process, args.session_id)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    break_signal = getattr(signal, "SIGBREAK", None)
    if break_signal is not None:
        signal.signal(break_signal, _handle_sigterm)


def handle_clean_shutdown(args: models.WatchdogArgs) -> None:
    mark_session_closing(args.session_id, args.sponsor_id)
    log.info(
        "clean shutdown complete",
        extra={
            "next_step": (
                "python -m capture.session_close "
                f"--session-id {args.session_id} --sponsor-id {args.sponsor_id} "
                "--xdf-path <path>"
            )
        },
    )


def record_unexpected_exit(
    args: models.WatchdogArgs,
    exit_code: int,
    restart_count: int,
    uptime_s: float,
) -> None:
    log.warning(
        "lsl_forwarder exited unexpectedly",
        extra={"exit_code": exit_code, "uptime_s": round(uptime_s, 2)},
    )

    # Log every crash to alert_events, including the final one that
    # tips the system over MAX_RESTARTS — all failures belong in audit.
    log_restart(
        session_id=args.session_id,
        participant_id=args.participant_id,
        site_id=args.site_id,
        sponsor_id=args.sponsor_id,
        exit_code=exit_code,
        restart_count=restart_count,
        uptime_s=uptime_s,
    )


def restart_delay_s(restart_count: int) -> float:
    return min(
        models.RESTART_DELAY_BASE_S * (2 ** (restart_count - 1)),
        models.RESTART_DELAY_MAX_S,
    )


def run_watchdog_loop(
    args: models.WatchdogArgs,
    forwarder_cmd: list[str],
    state: models.WatchdogState,
) -> int:
    while state.restart_count <= models.MAX_RESTARTS:
        log.info(
            "starting lsl_forwarder",
            extra={"restart_count": state.restart_count},
        )
        start_time = time.monotonic()
        state.process = start_forwarder(forwarder_cmd)
        exit_code = wait_for_forwarder(state.process)
        uptime_s = time.monotonic() - start_time

        if state.clean_shutdown and exit_code == 0:
            handle_clean_shutdown(args)
            return 0

        state.restart_count += 1
        record_unexpected_exit(args, exit_code, state.restart_count, uptime_s)

        if state.restart_count > models.MAX_RESTARTS:
            log.error(
                "max restarts exceeded — marking session failed",
                extra={"max_restarts": models.MAX_RESTARTS, "session_id": args.session_id},
            )
            mark_session_failed(args.session_id, args.sponsor_id)
            return 1

        delay = restart_delay_s(state.restart_count)
        log.info("waiting before restart", extra={"delay_s": delay})
        time.sleep(delay)
    return 1


def main() -> None:
    settings.validate()
    args = watchdog_args(parse_args())
    set_session_id(args.session_id)

    state = models.WatchdogState()
    install_signal_handlers(state, args)
    sys.exit(run_watchdog_loop(args, build_forwarder_cmd(args), state))
