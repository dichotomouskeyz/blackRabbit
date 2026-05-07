"""Consensai process watchdog.

Spawns lsl_forwarder as a subprocess, monitors it, and restarts it on
unexpected exit. Every restart is written to alert_events — the audit
trigger fires automatically, producing an audit_events entry.

On a clean SIGTERM the forwarder is signalled to stop, the watchdog
waits for it to flush and close the XDF file, then exits without logging
or restarting.

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


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Consensai process watchdog")
    p.add_argument("--session-id", required=True)
    p.add_argument("--participant-id", required=True)
    p.add_argument("--site-id", required=True)
    p.add_argument("--sponsor-id", required=True)
    return p.parse_args()


def _lookup_compound(session_id: str) -> tuple[str, float]:
    """Return (compound, compound_dose) from the sessions table."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT compound, compound_dose FROM sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()
            if row:
                return row[0], float(row[1] or 0.0)
            return "unknown", 0.0
    finally:
        conn.close()


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
    compound, compound_dose = _lookup_compound(session_id)
    params = json.dumps(
        {
            "exit_code": exit_code,
            "restart_count": restart_count,
            "uptime_s": round(uptime_s, 2),
        }
    )
    conn = psycopg2.connect(settings.DATABASE_URL)
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
            log.info("clean shutdown complete")
            break

        exit_code = process.returncode
        log.warning(
            "lsl_forwarder exited unexpectedly",
            extra={"exit_code": exit_code, "uptime_s": round(uptime_s, 2)},
        )

        restart_count += 1

        if restart_count > MAX_RESTARTS:
            log.error(
                "max restarts exceeded — giving up",
                extra={"max_restarts": MAX_RESTARTS},
            )
            break

        _log_restart(
            session_id=args.session_id,
            participant_id=args.participant_id,
            site_id=args.site_id,
            sponsor_id=args.sponsor_id,
            exit_code=exit_code,
            restart_count=restart_count,
            uptime_s=uptime_s,
        )

        delay = min(
            RESTART_DELAY_BASE_S * (2 ** (restart_count - 1)), RESTART_DELAY_MAX_S
        )
        log.info("waiting before restart", extra={"delay_s": delay})
        time.sleep(delay)


if __name__ == "__main__":
    main()
