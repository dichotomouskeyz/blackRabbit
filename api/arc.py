"""ARC read/run gating for the operator API (INV-006 / PRH-004).

The watermark gate is extracted here as a directly testable function so INV-006
is provable in M0 even though the ARC HTTP endpoints are capability-gated (409)
and never reach this code through the HTTP surface yet. When unblocked, the API
endpoints call `assert_session_arc_ready` BEFORE any ARC function (PAT-010 wrap,
not reimplement), with a non-null server `sponsor_id`.

`watermark_state` is derived from `sessions.status` + the watermark_verified /
watermark_failed audit events (migration 024) — never from temporal-alignment
checks, which `assert_arc_temporal_alignment` owns.
"""

# Read SQL constants (PAT-003 / INV-002). Both match ^(SELECT|WITH), no write
# token. IDs reach SQL as bound %(name)s params only (PRH-003).
SESSION_STATUS_FOR_ARC_SQL = (
    "SELECT status::text FROM sessions WHERE id = %(session_id)s AND sponsor_id = %(sponsor_id)s"
)
WATERMARK_EVENTS_FOR_ARC_SQL = (
    "SELECT event_type FROM audit_events "
    "WHERE session_id = %(session_id)s "
    "AND event_type IN ('watermark_verified', 'watermark_failed')"
)


class WatermarkNotVerified(Exception):
    """Raised when an ARC endpoint is reached for a non-`verified` session.

    Mapped to a 409 capability-status response at the HTTP layer.
    """

    def __init__(self, session_id: str, watermark_state: str) -> None:
        self.session_id = session_id
        self.watermark_state = watermark_state
        super().__init__(
            f"ARC unavailable until watermark verified; current state: {watermark_state}"
        )


class SessionNotFound(Exception):
    """Raised when a session id is not visible under the server sponsor."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"session {session_id} not found for this tenant")


def derive_watermark_state(conn, session_id: str, sponsor_id: str) -> str:
    """Derive watermark_state: not_started | in_progress | verified | failed.

    Queries `sessions.status` (tenancy-scoped by sponsor_id) and the terminal
    watermark audit events (migration 024). A terminal watermark event wins; in
    its absence the live status maps to not_started (initializing) vs
    in_progress (anything started but not terminal).
    """
    with conn.cursor() as cur:
        cur.execute(
            SESSION_STATUS_FOR_ARC_SQL,
            {"session_id": session_id, "sponsor_id": sponsor_id},
        )
        row = cur.fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        status = row[0]

        cur.execute(WATERMARK_EVENTS_FOR_ARC_SQL, {"session_id": session_id})
        events = {r[0] for r in cur.fetchall()}

    if "watermark_verified" in events:
        return "verified"
    if "watermark_failed" in events:
        return "failed"
    # No terminal watermark event yet — derive from live status.
    if status == "initializing":
        return "not_started"
    if status == "failed":
        return "failed"
    return "in_progress"


def assert_session_arc_ready(conn, session_id: str, sponsor_id: str) -> None:
    """Gate ARC read/run on watermark_state == "verified" (INV-006 / PRH-004).

    Queries `sessions.status` + watermark audit events in api/ FIRST (before any
    ARC function), and raises `WatermarkNotVerified` unless the derived state is
    "verified". Does NOT delegate to `assert_arc_temporal_alignment` (which
    checks temporal alignment only, not status). The caller passes a non-null
    server `sponsor_id`.
    """
    if sponsor_id is None:
        # Never call a wrapped contract / gate with a null tenant (INV-001).
        raise ValueError("assert_session_arc_ready requires a non-null sponsor_id")
    state = derive_watermark_state(conn, session_id, sponsor_id)
    if state != "verified":
        raise WatermarkNotVerified(session_id, state)
    return None
