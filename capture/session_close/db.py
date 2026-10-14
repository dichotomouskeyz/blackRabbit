"""Database state helpers for session close."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg2
import pylsl
from psycopg2.extras import Json

from capture.logger import get_logger
from config import settings

log = get_logger("session_close")

VALID_ENTRY_STATES = frozenset({"active", "closing"})


@dataclass(frozen=True, slots=True)
class SessionAlertContext:
    participant_id: str
    site_id: str
    sponsor_id: str
    compound: str
    compound_dose: float | None


def fetch_session_status(conn, session_id: str, sponsor_id: str) -> str | None:
    """Return the current status string, or None if not found."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM sessions WHERE id = %s AND sponsor_id = %s",
            (session_id, sponsor_id),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def fetch_session_alert_context(
    conn,
    session_id: str,
    sponsor_id: str,
) -> SessionAlertContext:
    """Return the session metadata needed to write an alert row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT participant_id, site_id, sponsor_id, compound, compound_dose
            FROM sessions
            WHERE id = %s AND sponsor_id = %s
            """,
            (session_id, sponsor_id),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"session {session_id!r} not found for sponsor {sponsor_id!r}")
    return SessionAlertContext(
        participant_id=str(row[0]),
        site_id=str(row[1]),
        sponsor_id=str(row[2]),
        compound=str(row[3]),
        compound_dose=None if row[4] is None else float(row[4]),
    )


def set_closing(conn, session_id: str, sponsor_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET status = 'closing' "
            "WHERE id = %s AND sponsor_id = %s AND status = 'active'",
            (session_id, sponsor_id),
        )
    conn.commit()


def connect_db():
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = False
        return conn
    except psycopg2.OperationalError as exc:
        log.error("DB connection failed", extra={"error": str(exc)})
        return None


def validate_entry_state(conn, session_id: str, sponsor_id: str) -> str | None:
    status = fetch_session_status(conn, session_id, sponsor_id)
    if status is None:
        log.error("session not found", extra={"session_id": session_id, "sponsor_id": sponsor_id})
        return None
    if status not in VALID_ENTRY_STATES:
        log.error(
            "session is not in a closeable state",
            extra={"session_id": session_id, "current_status": status},
        )
        return None
    return status


def ensure_closing(conn, session_id: str, sponsor_id: str, status: str) -> None:
    if status != "active":
        return

    log.warning(
        "closing an active session after capture lock and complete XDF verification",
        extra={"session_id": session_id},
    )
    set_closing(conn, session_id, sponsor_id)
    log.info(
        "session status changed to closing",
        extra={"session_id": session_id, "sponsor_id": sponsor_id},
    )


def log_arc_failure_alert(
    session_id: str,
    sponsor_id: str,
    algorithm_version: str,
    algorithm_parameters: dict,
    message: str,
    severity: str = "critical",
) -> None:
    """Write a queryable ARC failure alert_event on its own connection."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        context = fetch_session_alert_context(conn, session_id, sponsor_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_events (
                    session_id, participant_id, site_id, sponsor_id,
                    alert_type, compound, compound_dose, severity,
                    algorithm_name, algorithm_version, algorithm_parameters,
                    message, lsl_timestamp
                ) VALUES (%s, %s, %s, %s,
                          'arc_failure', %s, %s, %s,
                          'arc_post_session', %s, %s::jsonb,
                          %s, %s)
                """,
                (
                    session_id,
                    context.participant_id,
                    context.site_id,
                    context.sponsor_id,
                    context.compound,
                    context.compound_dose,
                    severity,
                    algorithm_version,
                    Json(algorithm_parameters),
                    message,
                    pylsl.local_clock(),
                ),
            )
        conn.commit()
        log.error(
            "ARC failure logged to alert_events",
            extra={"session_id": session_id, "sponsor_id": sponsor_id},
        )
    except Exception as exc:
        log.error(
            "failed to write ARC failure alert",
            extra={"error": str(exc), "session_id": session_id, "sponsor_id": sponsor_id},
        )
    finally:
        conn.close()
