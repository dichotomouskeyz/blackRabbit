"""Watchdog database writes."""

import json

import psycopg2

from capture.logger import get_logger
from capture.watchdog import models
from config import settings

log = get_logger("watchdog")


def lookup_compound(conn: "psycopg2.extensions.connection", session_id: str) -> tuple[str, float]:
    """Return (compound, compound_dose) using the supplied connection."""
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


def log_restart(
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
    compound, compound_dose = lookup_compound(conn, session_id)
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
                    models.WATCHDOG_ALGORITHM_NAME,
                    models.WATCHDOG_ALGORITHM_VERSION,
                    params,
                    f"lsl_forwarder exited with code {exit_code}, "
                    f"restarting (attempt {restart_count}/{models.MAX_RESTARTS})",
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


def mark_session_closing(session_id: str) -> None:
    """Transition session active->closing after the forwarder stops cleanly."""
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sessions SET status = 'closing' WHERE id = %s AND status = 'active'",
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


def mark_session_failed(session_id: str) -> None:
    """Set session status to failed after max restarts are exhausted."""
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
