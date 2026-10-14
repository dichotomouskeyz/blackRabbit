"""Tenant-scoped reads of persisted ARC artifacts, gated by capture verification."""

SESSION_STATUS_FOR_ARC_SQL = (
    "SELECT status::text, voided_from::text FROM sessions WHERE id = %(session_id)s "
    "AND sponsor_id = %(sponsor_id)s AND site_id = %(site_id)s"
)
WATERMARK_EVENTS_FOR_ARC_SQL = (
    "SELECT a.event_type FROM audit_events a JOIN sessions s ON s.id = a.session_id "
    "WHERE s.id = %(session_id)s AND s.sponsor_id = %(sponsor_id)s "
    "AND s.site_id = %(site_id)s "
    "AND a.event_type IN ('watermark_verified', 'watermark_failed')"
)
LATEST_ANALYSIS_SQL = (
    "SELECT a.id::text, a.created_at, a.algorithm_version, a.config_sha256, "
    "a.input_sha256, a.artifact_sha256, a.artifact "
    "FROM analysis_runs a JOIN sessions s ON s.id = a.session_id "
    "AND s.sponsor_id = a.sponsor_id AND s.site_id = a.site_id "
    "WHERE s.id = %(session_id)s AND s.sponsor_id = %(sponsor_id)s "
    "AND s.site_id = %(site_id)s ORDER BY a.created_at DESC, a.id DESC LIMIT 1"
)


class WatermarkNotVerified(Exception):
    """A visible session has not completed verified capture; HTTP 409."""

    def __init__(self, session_id: str, watermark_state: str) -> None:
        self.session_id = session_id
        self.watermark_state = watermark_state
        super().__init__(
            f"ARC unavailable until watermark verified; current state: {watermark_state}"
        )


class SessionVoided(Exception):
    """The session was voided; analysis is withheld (session-void SV-006). HTTP 409."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"session {session_id} is voided")


class SessionNotFound(Exception):
    """The session is not visible under the server sponsor and site."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"session {session_id} not found for this tenant")


def derive_watermark_state(conn, session_id: str, sponsor_id: str, site_id: str) -> str:
    """Derive not_started | in_progress | verified | failed from scoped state.

    Historical verification cannot authorize a session whose current lifecycle
    is no longer closed. The caller uses one read-only transaction snapshot.
    """
    if not sponsor_id or not site_id:
        raise ValueError("watermark reads require sponsor_id and site_id")
    scope = {"session_id": session_id, "sponsor_id": sponsor_id, "site_id": site_id}
    with conn.cursor() as cur:
        cur.execute(SESSION_STATUS_FOR_ARC_SQL, scope)
        row = cur.fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        # A voided session reports the watermark of the lifecycle it replaced.
        status = row[1] if row[0] == "voided" else row[0]
        cur.execute(WATERMARK_EVENTS_FOR_ARC_SQL, scope)
        events = {r[0] for r in cur.fetchall()}

    if status == "failed":
        return "failed"
    if status == "closed" and "watermark_verified" in events:
        return "verified"
    if "watermark_failed" in events:
        return "failed"
    if status == "initializing":
        return "not_started"
    return "in_progress"


def assert_session_arc_ready(conn, session_id: str, sponsor_id: str, site_id: str) -> None:
    """Reject ARC reads unless the scoped capture has a verified watermark and is not voided."""
    state = derive_watermark_state(conn, session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            SESSION_STATUS_FOR_ARC_SQL,
            {"session_id": session_id, "sponsor_id": sponsor_id, "site_id": site_id},
        )
        row = cur.fetchone()
    if row is not None and row[0] == "voided":
        raise SessionVoided(session_id)
    if state != "verified":
        raise WatermarkNotVerified(session_id, state)


def latest_artifact(conn, session_id: str, sponsor_id: str, site_id: str) -> dict | None:
    """Return the latest persisted report and provenance, without running ARC."""
    assert_session_arc_ready(conn, session_id, sponsor_id, site_id)
    with conn.cursor() as cur:
        cur.execute(
            LATEST_ANALYSIS_SQL,
            {"session_id": session_id, "sponsor_id": sponsor_id, "site_id": site_id},
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "session_id": session_id,
        "analysis_id": row[0],
        "created_at": row[1].isoformat(),
        "provenance": {
            "algorithm_version": row[2],
            "config_sha256": row[3],
            "input_sha256": row[4],
            "artifact_sha256": row[5],
        },
        "artifact": row[6],
    }
