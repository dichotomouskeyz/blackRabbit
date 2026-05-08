"""Consensai process watchdog.

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

import argparse
import json
import signal
import subprocess
import sys
import time
import uuid

import psycopg2

from capture.logger import get_logger, set_session_id
from config import settings

settings.validate()

log = get_logger("watchdog")

WATCHDOG_ALGORITHM_NAME = "watchdog"
WATCHDOG_ALGORITHM_VERSION = "1.0.0"

# Restart policy
MAX_RESTARTS = 5
RESTART_DELAY_BASE_S = 5.0
RESTART_DELAY_MAX_S = 60.0


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Consensai process watchdog")
    p.add_argument("--session-id", required=True, type=_parse_uuid, help="Session UUID")
    p.add_argument(
        "--participant-id",
        required=True,
        type=_parse_uuid,
        help="Pseudonymous participant UUID",
    )
    p.add_argument("--site-id", required=True, type=_parse_uuid, help="Site UUID")
    p.add_argument("--sponsor-id", required=True, type=_parse_uuid, help="Sponsor UUID")
    return p.parse_args()


def _lookup_compound(
    conn: "psycopg2.extensions.connection", session_id: str
) -> tuple[str, float]:
    """Return (compound, compound_dose) using the supplied connection.

    Raises RuntimeError if the session row is not found — a missing session
    is a data integrity failure, not a recoverable condition.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT compound, compound_dose FROM sessions WHERE id = %s",
            (session_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise RuntimeError(
            f"Session {session_id!r} not found in sessions table — "
            "compound is required and cannot be inferred"
        )
    return row[0], float(row[1] or 0.0)


def _log_restart(
    session_id: str,
    participant_id: str,
    site_id: str,
    sponsor_id: str,
    exit_code: int,
    restart_count: int,
    uptime_s: float,
) -> None:
    """Insert a process_restart alert_event. Audit trigger fires automatically."""
    params = json.dumps(
        {
            "exit_code": exit_code,
            "restart_count": restart_count,
            "uptime_s": round(uptime_s, 2),
        }
    )
    conn = psycopg2.connect(settings.DATABASE_URL)
    compound, compound_dose = _lookup_compound(conn, session_id)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (
                    session_id, participant_id, site_id, sponsor_id,
                    alert_type, compound, compound_dose, severity,
                    algorithm_name, algorithm_version, algorithm_parameters,
                    message
                ) VALUES (%s, %s, %s, %s,
                          'process_restart', %s, %s, 'warning',
                          %s, %s, %s::jsonb,
                          %s)
                """,
                (
                    session_id,
                    participant_id,
                    site_id,
                    sponsor_id,
                    compound,
                    compound_dose,
                    WATCHDOG_ALGORITHM_NAME,
                    WATCHDOG_ALGORITHM_VERSION,
                    params,
                    f"lsl_forwarder exited with code {exit_code}, "
                    f"restarting (attempt {restart_count}/{MAX_RESTARTS})",
                ),
            )
        conn.commit()
        log.info(
            "restart logged to alert_events",
            extra={
                "exit_code": exit_code,
                "restart_count": restart_count,
                "uptime_s": round(uptime_s, 2),
            },
        )
    except Exception as exc:
        log.error("failed to write restart alert", extra={"error": str(exc)})
    finally:
        conn.close()


def _mark_session_closing(session_id: str) -> None:
    """Transition session active→closing after the forwarder stops cleanly.

    'closing' is the signal to session_close.py that the XDF file is
    complete and it is safe to begin reconciliation.  The transition is
    conditional (WHERE status = 'active') so it is a no-op if something
    else already moved the session forward.
    """
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET status = 'closing' "
                    "WHERE id = %s AND status = 'active'",
                    (session_id,),
                )
            conn.commit()
            log.info(
                "session status → closing — run session_close to reconcile",
                extra={"session_id": session_id},
            )
        finally:
            conn.close()
    except Exception as exc:
        log.error(
            "failed to set session to closing",
            extra={"error": str(exc), "session_id": session_id},
        )


def _mark_session_failed(session_id: str) -> None:
    """Set session status to failed after max restarts are exhausted.

    Fires the sessions_watermark_trigger which writes watermark_failed to
    audit_events, permanently blocking post-session batch processing.
    The conditional WHERE clause prevents double-writes if the session
    was already moved to a terminal state.
    """
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET status = 'failed', closed_at = NOW() "
                    "WHERE id = %s AND status IN ('active', 'closing')",
                    (session_id,),
                )
            conn.commit()
            log.error(
                "session marked failed — watermark_failed written to audit_events",
                extra={"session_id": session_id},
            )
        finally:
            conn.close()
    except Exception as exc:
        log.error(
            "failed to mark session as failed",
            extra={"error": str(exc), "session_id": session_id},
        )


def main() -> None:
    args = _parse_args()
    set_session_id(args.session_id)

    forwarder_cmd = [
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

    restart_count = 0
    clean_shutdown = False

    def _handle_sigterm(signum, frame):
        nonlocal clean_shutdown
        clean_shutdown = True
        if process and process.poll() is None:
            log.info("SIGTERM received — stopping forwarder")
            process.terminate()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    process = None

    while restart_count <= MAX_RESTARTS:
        log.info(
            "starting lsl_forwarder",
            extra={"restart_count": restart_count},
        )
        start_time = time.monotonic()
        process = subprocess.Popen(forwarder_cmd)  # nosec B603
        process.wait()
        uptime_s = time.monotonic() - start_time

        if clean_shutdown:
            _mark_session_closing(args.session_id)
            log.info(
                "clean shutdown complete",
                extra={
                    "next_step": (
                        "python -m capture.session_close "
                        f"--session-id {args.session_id} --xdf-path <path>"
                    )
                },
            )
            break

        exit_code = process.returncode
        log.warning(
            "lsl_forwarder exited unexpectedly",
            extra={"exit_code": exit_code, "uptime_s": round(uptime_s, 2)},
        )

        restart_count += 1

        # Log every crash to alert_events, including the final one that
        # tips the system over MAX_RESTARTS — all failures belong in audit.
        _log_restart(
            session_id=args.session_id,
            participant_id=args.participant_id,
            site_id=args.site_id,
            sponsor_id=args.sponsor_id,
            exit_code=exit_code,
            restart_count=restart_count,
            uptime_s=uptime_s,
        )

        if restart_count > MAX_RESTARTS:
            log.error(
                "max restarts exceeded — marking session failed",
                extra={"max_restarts": MAX_RESTARTS, "session_id": args.session_id},
            )
            _mark_session_failed(args.session_id)
            break

        delay = min(
            RESTART_DELAY_BASE_S * (2 ** (restart_count - 1)), RESTART_DELAY_MAX_S
        )
        log.info("waiting before restart", extra={"delay_s": delay})
        time.sleep(delay)


if __name__ == "__main__":
    main()
