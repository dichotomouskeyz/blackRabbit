"""Void a closed or failed session (session-void SV-001..SV-005).

Voiding replaces a terminal status with `voided` and records when, why and from
which status. It never deletes samples, events, XDF files or analysis rows. The
status-transition and full-row audit triggers record the change; this module
writes no audit rows.
"""

import uuid

import psycopg2

from config import settings

VOIDABLE_STATUSES = ("closed", "failed")
MIN_REASON_LEN = 3
MAX_REASON_LEN = 500

# One statement, scoped by tenant and limited to voidable statuses, so a race
# with another writer cannot void an active session.
_VOID_SQL = (
    "UPDATE sessions SET status = 'voided', voided_at = NOW(), "
    "void_reason = %(reason)s, voided_from = status "
    "WHERE id = %(session_id)s AND sponsor_id = %(sponsor_id)s AND site_id = %(site_id)s "
    "AND status IN ('closed', 'failed') "
    "RETURNING voided_at"
)
_STATUS_SQL = (
    "SELECT status::text FROM sessions "
    "WHERE id = %(session_id)s AND sponsor_id = %(sponsor_id)s AND site_id = %(site_id)s"
)
_LOCK_SQL = "SELECT pg_try_advisory_xact_lock(hashtextextended(%(session_id)s, 0))"


class SessionNotFound(LookupError):
    """No session with this ID under the tenant scope."""


class SessionAlreadyVoided(RuntimeError):
    """The session is already voided."""


class SessionNotVoidable(RuntimeError):
    """The session is not closed or failed."""

    def __init__(self, status: str):
        super().__init__(f"session status {status!r} cannot be voided; capture must end first")
        self.status = status


class SessionBusy(RuntimeError):
    """Capture, closeout, recovery or ARC holds the session lock."""


def clean_reason(reason: object) -> str:
    """The trimmed reason, or ValueError when it is missing or out of bounds."""
    if not isinstance(reason, str):
        raise ValueError("reason is required")
    text = reason.strip()
    if not MIN_REASON_LEN <= len(text) <= MAX_REASON_LEN:
        raise ValueError(f"reason must be {MIN_REASON_LEN} to {MAX_REASON_LEN} characters")
    return text


def void_session(*, session_id: str, sponsor_id: str, site_id: str, reason: str) -> dict:
    """Void a session and return {session_id, status, voided_at}.

    Raises SessionNotFound, SessionAlreadyVoided, SessionNotVoidable or
    SessionBusy. Input is validated before any connection opens.
    """
    session_id = str(uuid.UUID(session_id))
    if not sponsor_id or not site_id:
        raise ValueError("void_session requires sponsor_id and site_id")
    text = clean_reason(reason)
    params = {
        "session_id": session_id,
        "sponsor_id": sponsor_id,
        "site_id": site_id,
        "reason": text,
    }

    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            # The transaction-scoped lock shares the key used by capture,
            # closeout, recovery and ARC.
            cur.execute(_LOCK_SQL, params)
            locked = cur.fetchone()
            if not locked or not locked[0]:
                raise SessionBusy("session is busy with capture, closeout, recovery or ARC")
            cur.execute(_VOID_SQL, params)
            row = cur.fetchone()
            if row is None:
                cur.execute(_STATUS_SQL, params)
                current = cur.fetchone()
                if current is None:
                    raise SessionNotFound(session_id)
                if current[0] == "voided":
                    raise SessionAlreadyVoided(session_id)
                raise SessionNotVoidable(current[0])
    finally:
        conn.close()
    return {"session_id": session_id, "status": "voided", "voided_at": row[0].isoformat()}
