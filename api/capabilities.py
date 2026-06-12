"""Capability-status matrix and gating helpers (PAT-011 / INV-013).

This module is the single source of truth for the Capability Status matrix
(spec "Capability Status matrix"). `GET /capabilities` serializes it, and the
gated endpoints look up their row here — neither hardcodes the matrix
elsewhere.

Each row: {capability, endpoint, status, blocked_reason, gate}. `status` is one
of implemented | scaffolded | blocked.
"""

# Endpoint labels match the spec discovery contract (the `{id}` path form used
# by GET /capabilities). The route table uses `{session_id}`; the matrix is the
# documented, human-facing label.
CAPABILITY_MATRIX: list[dict] = [
    {
        "capability": "health",
        "endpoint": "GET /health",
        "status": "implemented",
        "blocked_reason": None,
        "gate": None,
    },
    {
        "capability": "vocab",
        "endpoint": "GET /vocab",
        "status": "implemented",
        "blocked_reason": None,
        "gate": None,
    },
    {
        "capability": "list_sessions",
        "endpoint": "GET /sessions",
        "status": "implemented",
        "blocked_reason": None,
        "gate": None,
    },
    {
        "capability": "session_status",
        "endpoint": "GET /sessions/{id}/status",
        "status": "implemented",
        "blocked_reason": None,
        "gate": None,
    },
    {
        "capability": "create_session",
        "endpoint": "POST /sessions",
        "status": "implemented",
        "blocked_reason": None,
        "gate": None,
    },
    {
        "capability": "capabilities",
        "endpoint": "GET /capabilities",
        "status": "implemented",
        "blocked_reason": None,
        "gate": None,
    },
    {
        "capability": "live_signals",
        "endpoint": "WS /sessions/{id}/stream",
        "status": "scaffolded",
        "blocked_reason": "live biosignal tap not built in M0; WS upgrade refused",
        "gate": "OQ-003",
    },
    {
        "capability": "arc_review",
        "endpoint": "GET /sessions/{id}/arc",
        "status": "scaffolded",
        "blocked_reason": "ARC review surface not built in M0",
        "gate": "OQ-001",
    },
    {
        "capability": "log_marker",
        "endpoint": "POST /sessions/{id}/markers",
        "status": "blocked",
        "blocked_reason": "marker publish via LSL outlet not enabled until auth lands",
        "gate": "OQ-001",
    },
    {
        "capability": "capture_start",
        "endpoint": "POST /sessions/{id}/capture:start",
        "status": "blocked",
        "blocked_reason": "capture process ownership unsettled",
        "gate": "OQ-004",
    },
    {
        "capability": "capture_stop",
        "endpoint": "POST /sessions/{id}/capture:stop",
        "status": "blocked",
        "blocked_reason": "capture process ownership unsettled",
        "gate": "OQ-004",
    },
    {
        "capability": "close_session",
        "endpoint": "POST /sessions/{id}/close",
        "status": "blocked",
        "blocked_reason": "session close not enabled until auth lands",
        "gate": "OQ-001",
    },
    {
        "capability": "arc_run",
        "endpoint": "POST /sessions/{id}/arc:run",
        "status": "blocked",
        "blocked_reason": "ARC run not enabled until auth lands",
        "gate": "OQ-001",
    },
]

# Endpoint-label -> row, for O(1) lookup by the gated routes.
_BY_ENDPOINT = {row["endpoint"]: row for row in CAPABILITY_MATRIX}


def capability_for_endpoint(endpoint: str) -> dict | None:
    """Return the matrix row for an endpoint label, or None."""
    return _BY_ENDPOINT.get(endpoint)


def capability_unavailable_body(endpoint: str) -> dict:
    """Build the structured 409 capability-status body for an endpoint label.

    Shape (spec capability-status contract):
        {error, capability, status, blocked_reason, gate}
    """
    row = capability_for_endpoint(endpoint)
    if row is None:
        raise KeyError(f"no capability row for endpoint {endpoint!r}")
    return {
        "error": "capability_unavailable",
        "capability": row["capability"],
        "status": row["status"],
        "blocked_reason": row["blocked_reason"],
        "gate": row["gate"],
    }
