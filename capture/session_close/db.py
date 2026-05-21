"""Database state helpers for session close."""

import psycopg2

from capture.logger import get_logger
from config import settings

log = get_logger("session_close")

VALID_ENTRY_STATES = frozenset({"active", "closing"})


def fetch_session_status(conn, session_id: str, sponsor_id: str) -> str | None:
    """Return the current status string, or None if not found."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM sessions WHERE id = %s AND sponsor_id = %s",
            (session_id, sponsor_id),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


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
        "session is still 'active' — watchdog may not have stopped the "
        "forwarder; XDF may be incomplete if capture is still running. "
        "Expected sequence: SIGTERM watchdog → watchdog exits → session_close.",
        extra={"session_id": session_id},
    )
    set_closing(conn, session_id, sponsor_id)
    log.info("session status → closing", extra={"session_id": session_id, "sponsor_id": sponsor_id})
