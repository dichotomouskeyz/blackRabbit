"""Session read/create wrappers (PAT-010).

Read SQL lives as module-level constants (PAT-003), each matching ^(SELECT|WITH)
with no write token (INV-002), with IDs bound as %(name)s params (PRH-003). All
reads run on the read-only connection (INV-002) and filter by the server
sponsor and site (INV-001). Creates wrap `capture.session_init.workflow.create_session`
via module-attribute access so test monkeypatches bind.
"""

import uuid

# IMPORTANT: module-attribute access (not `from ... import create_session`) so
# tests that monkeypatch `workflow.create_session` bind at call time.
import capture.session_init.workflow as session_init_workflow
from api import arc

# --- Read SQL (PAT-003 / INV-002) -------------------------------------------
# Pinned columns per RS-019 (sessions table, migration 002/023).
SESSIONS_LIST_SQL = (
    "SELECT id::text, status::text, compound, started_at, closed_at, created_at "
    "FROM sessions "
    "WHERE sponsor_id = %(sponsor_id)s AND site_id = %(site_id)s "
    "ORDER BY created_at DESC"
)
SESSION_STATUS_SQL = (
    "SELECT id::text, status::text, started_at, closed_at "
    "FROM sessions "
    "WHERE id = %(session_id)s AND sponsor_id = %(sponsor_id)s AND site_id = %(site_id)s"
)


def _iso(value):
    """Serialize a datetime to ISO-8601, or pass through None."""
    return value.isoformat() if value is not None else None


def list_sessions(conn, sponsor_id: str, site_id: str) -> dict:
    """Tenancy-scoped session list (INV-001).

    Returns {sessions: [{id, status, compound, started_at, closed_at,
    created_at}]} filtered by the server sponsor and site.
    """
    if not sponsor_id or not site_id:
        raise ValueError("list_sessions requires sponsor_id and site_id (INV-001)")
    with conn.cursor() as cur:
        cur.execute(SESSIONS_LIST_SQL, {"sponsor_id": sponsor_id, "site_id": site_id})
        rows = cur.fetchall()
    sessions = [
        {
            "id": r[0],
            "status": r[1],
            "compound": r[2],
            "started_at": _iso(r[3]),
            "closed_at": _iso(r[4]),
            "created_at": _iso(r[5]),
        }
        for r in rows
    ]
    return {"sessions": sessions}


def session_status(conn, session_id: str, sponsor_id: str, site_id: str) -> dict | None:
    """Tenancy-scoped status + derived watermark_state (RS-016).

    Returns the status payload, or None when the session is not visible under
    the server sponsor/site (caller maps None -> 404). watermark_state is the closed
    enum derived in api/ (never a {verified, failed} bool pair).
    """
    if not sponsor_id or not site_id:
        raise ValueError("session_status requires sponsor_id and site_id (INV-001)")
    with conn.cursor() as cur:
        cur.execute(
            SESSION_STATUS_SQL,
            {"session_id": session_id, "sponsor_id": sponsor_id, "site_id": site_id},
        )
        row = cur.fetchone()
    if row is None:
        return None
    watermark_state = arc.derive_watermark_state(conn, session_id, sponsor_id, site_id)
    return {
        "id": row[0],
        "status": row[1],
        "started_at": _iso(row[2]),
        "closed_at": _iso(row[3]),
        "watermark_state": watermark_state,
    }


# --- Create allow-list (RS-004 / INV-004) -----------------------------------
# The closed set of optional kwargs the API forwards to create_session, mirrored
# from the create_session signature (sourced from session_signal_metadata). The
# API constructs the call from this allow-list and never spreads **kwargs.
_OPTIONAL_CREATE_KWARGS = (
    "compound_dose",
    "compound_dose_unit",
    "protocol_arm",
    "room_id",
    "eeg_sensor_form",
    "eeg_electrode_system",
    "eeg_electrode_type",
    "hrv_electrode_placement",
    "hrv_electrode_type",
    "eda_electrode_placement",
    "eda_electrode_type",
    "eda_skin_prep",
)


def create_session(*, compound, capture_source, participant_id, sponsor_id, site_id, **optional):
    """Wrap `session_init.workflow.create_session` (PAT-010).

    Tenancy (`sponsor_id`/`site_id`) is supplied by the server, never the
    client. Forwards only the allow-listed optional kwargs. Returns the new
    session id. The caller validates participant_id as a UUID first (INV-005);
    create_session re-validates pre-DB and raises ValueError for bad enums.
    """
    if sponsor_id is None or site_id is None:
        raise ValueError("create_session requires non-null tenancy (INV-001)")
    forwarded = {
        k: v for k, v in optional.items() if k in _OPTIONAL_CREATE_KWARGS and v is not None
    }
    return session_init_workflow.create_session(
        compound=compound,
        site_id=site_id,
        sponsor_id=sponsor_id,
        participant_id=participant_id,
        capture_source=capture_source,
        **forwarded,
    )


def is_uuid(value: str) -> bool:
    """True iff value is a well-formed UUID (INV-004 path/field validation)."""
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True
