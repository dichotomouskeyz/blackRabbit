"""GET /capabilities (INV-013 discovery) — full Capability Status matrix.

Returns [{capability, endpoint, status, blocked_reason, gate}] matching the
spec's Capability Status matrix; `implemented` rows present.
"""

# Expected (capability-ish endpoint, status) pairs from the spec matrix (M0).
# We assert on endpoints + statuses since capability labels may vary slightly;
# every documented capability must be discoverable with the right status.
_EXPECTED_STATUS_BY_ENDPOINT = {
    "GET /health": "implemented",
    "GET /vocab": "implemented",
    "GET /sessions": "implemented",
    "GET /sessions/{id}/status": "implemented",
    "POST /sessions": "implemented",
    "GET /capabilities": "implemented",
    "WS /sessions/{id}/stream": "scaffolded",
    "GET /sessions/{id}/arc": "implemented",
    "POST /sessions/{id}/markers": "blocked",
    "POST /sessions/{id}/capture:start": "blocked",
    "POST /sessions/{id}/capture:stop": "blocked",
    "POST /sessions/{id}/close": "blocked",
    "POST /sessions/{id}/arc:run": "blocked",
}


def test_capabilities_returns_full_matrix(client):
    # Tests INV-013 [integration]: discovery endpoint returns the whole matrix.
    resp = client.get("/capabilities")
    assert resp.status_code == 200
    matrix = resp.json()
    assert isinstance(matrix, list) and matrix, "/capabilities must return a non-empty list"
    for row in matrix:
        assert {"capability", "endpoint", "status", "blocked_reason", "gate"} <= set(row), (
            f"capability row missing required keys: {row}"
        )
        assert row["status"] in ("implemented", "scaffolded", "blocked")


def test_capabilities_matrix_has_implemented_rows(client):
    # Tests INV-013 [integration]: implemented rows present.
    matrix = client.get("/capabilities").json()
    statuses = {row["status"] for row in matrix}
    assert "implemented" in statuses
    assert "scaffolded" in statuses
    assert "blocked" in statuses


def test_capabilities_matrix_covers_every_documented_capability(client):
    # Tests INV-013 [integration]: each documented endpoint has the right status.
    matrix = client.get("/capabilities").json()
    by_endpoint = {row["endpoint"]: row["status"] for row in matrix}
    for endpoint, expected in _EXPECTED_STATUS_BY_ENDPOINT.items():
        assert endpoint in by_endpoint, f"capability matrix missing endpoint {endpoint}"
        assert by_endpoint[endpoint] == expected, (
            f"{endpoint}: expected status {expected}, got {by_endpoint[endpoint]}"
        )
