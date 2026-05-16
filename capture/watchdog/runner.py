"""untitledplatform_1a process watchdog.

Spawns lsl_forwarder as a subprocess, monitors it, and restarts it on
unexpected exit. Every restart is written to alert_events — the audit
trigger fires automatically, producing an audit_events entry.

Session lifecycle handoff
-------------------------
The watchdog owns two session state transitions:

  active → closing   (clean shutdown)
    Send SIGTERM to the watchdog process. The watchdog forwards SIGTERM
    to lsl_forwarder, waits for it to flush buffers and close the XDF
    file, then sets session status = 'closing'. Only after the watchdog
    exits should the coordinator run session_close.py. Running
    session_close while the forwarder is still writing will produce an
    incomplete XDF and a false reconciliation failure.

    Correct sequence:
      1. kill -TERM <watchdog_pid>
      2. wait for watchdog to exit (poll or join)
      3. python -m capture.session_close --session-id <sid> --xdf-path <path>

  active → failed   (max restarts exhausted)
    If lsl_forwarder crashes more than MAX_RESTARTS times the watchdog
    sets session status = 'failed'. The sessions_watermark_trigger fires
    and writes watermark_failed to audit_events, permanently blocking
    post-session batch processing for this session. The coordinator is
    responsible for reviewing alert_events and deciding next steps.

Usage (matches lsl_forwarder args exactly):
    python -m capture.watchdog \\
        --session-id  <uuid> \\
        --participant-id <pseudonymous-token> \\
        --site-id     <site-code> \\
        --sponsor-id  <sponsor-code>
"""

import signal
import time

from capture.logger import get_logger, set_session_id
from capture.watchdog import models
from capture.watchdog.cli import build_forwarder_cmd, parse_args, watchdog_args
from capture.watchdog.db import log_restart, mark_session_closing, mark_session_failed
from capture.watchdog.process import start_forwarder, stop_forwarder, wait_for_forwarder
from config import settings

settings.validate()

log = get_logger("watchdog")


def install_signal_handlers(state: models.WatchdogState, args: models.WatchdogArgs) -> None:
    def _handle_sigterm(signum, frame):
        state.clean_shutdown = True
        process = state.process
        if process and process.poll() is None:
            log.info("SIGTERM received — stopping forwarder")
            stop_forwarder(process, args.session_id)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_sigterm)


def handle_clean_shutdown(args: models.WatchdogArgs) -> None:
    mark_session_closing(args.session_id)
    log.info(
        "clean shutdown complete",
        extra={
            "next_step": (
                f"python -m capture.session_close --session-id {args.session_id} --xdf-path <path>"
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
) -> None:
    while state.restart_count <= models.MAX_RESTARTS:
        log.info(
            "starting lsl_forwarder",
            extra={"restart_count": state.restart_count},
        )
        start_time = time.monotonic()
        state.process = start_forwarder(forwarder_cmd)
        exit_code = wait_for_forwarder(state.process)
        uptime_s = time.monotonic() - start_time

        if state.clean_shutdown:
            handle_clean_shutdown(args)
            break

        state.restart_count += 1
        record_unexpected_exit(args, exit_code, state.restart_count, uptime_s)

        if state.restart_count > models.MAX_RESTARTS:
            log.error(
                "max restarts exceeded — marking session failed",
                extra={"max_restarts": models.MAX_RESTARTS, "session_id": args.session_id},
            )
            mark_session_failed(args.session_id)
            break

        delay = restart_delay_s(state.restart_count)
        log.info("waiting before restart", extra={"delay_s": delay})
        time.sleep(delay)


def main() -> None:
    args = watchdog_args(parse_args())
    set_session_id(args.session_id)

    state = models.WatchdogState()
    install_signal_handlers(state, args)
    run_watchdog_loop(args, build_forwarder_cmd(args), state)
