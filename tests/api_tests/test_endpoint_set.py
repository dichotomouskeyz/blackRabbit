"""INV-012a — FastAPI is the agent trust boundary.

STRUCTURAL half: the app exposes exactly the documented endpoint set; unknown
paths -> 404; the WS route is present. These prove the route TABLE shape.

BEHAVIORAL half (B4 fix): the structural checks alone don't prove the server
OWNS tenancy — a route can exist and still trust a client/model-supplied tenant
scope. So we add a behavioral assertion: a request carrying a tenant scope
(`sponsor_id`/`site_id` in the body) is rejected (422). This reuses INV-004's
body-tenancy expectation and proves FastAPI — not the client/model/registry —
owns tenancy at the TB-004 boundary.
"""

from tests.api_tests.support import _INT_PARTICIPANT, _UNIT_VALID_COMPOUND

# The exact documented HTTP route set (method, path-template). WS handled below.
_EXPECTED_HTTP_ROUTES = {
    ("GET", "/health"),
    ("GET", "/capabilities"),
    ("GET", "/vocab"),
    ("GET", "/sessions"),
    ("GET", "/sessions/{session_id}/status"),
    ("POST", "/sessions"),
    ("GET", "/sessions/{session_id}/arc"),
    ("POST", "/sessions/{session_id}/void"),  # session-void spec
    ("POST", "/sessions/{session_id}/markers"),
    ("POST", "/sessions/{session_id}/capture:start"),
    ("POST", "/sessions/{session_id}/capture:stop"),
    ("POST", "/sessions/{session_id}/close"),
    ("POST", "/sessions/{session_id}/arc:run"),
    ("POST", "/agent/chat"),
}


def _http_routes(app):
    routes = set()
    for r in app.routes:
        methods = getattr(r, "methods", None)
        path = getattr(r, "path", None)
        if not methods or path is None:
            continue
        for m in methods:
            if m in {"HEAD", "OPTIONS"}:
                continue
            routes.add((m, path))
    return routes


def test_app_exposes_exactly_documented_routes(app):
    # Tests INV-012a [unit/integration]: exact documented endpoint set, nothing extra.
    actual = _http_routes(app)
    # Ignore FastAPI's auto docs/openapi routes.
    actual = {
        (m, p) for (m, p) in actual if not p.startswith(("/docs", "/redoc", "/openapi", "/static"))
    }
    missing = _EXPECTED_HTTP_ROUTES - actual
    extra = actual - _EXPECTED_HTTP_ROUTES
    assert not missing, f"missing documented routes: {missing}"
    assert not extra, f"app exposes undocumented routes (boundary leak): {extra}"


def test_unknown_path_returns_404(client):
    # Tests INV-012a [integration]: unknown endpoint path -> 404.
    resp = client.get("/sessions/this-is-not-an-endpoint/wat")
    assert resp.status_code == 404


def test_ws_stream_route_present(app):
    # Tests INV-012a / INV-008a [unit, structural]: the documented WS route exists.
    ws_paths = {getattr(r, "path", None) for r in app.routes}
    assert "/sessions/{session_id}/stream" in ws_paths, (
        "the scaffolded WS /sessions/{id}/stream route must be present"
    )


def test_server_rejects_client_supplied_tenant_scope(client):
    # Tests INV-012a [integration, BEHAVIORAL]: a request carrying a client/model
    # tenant scope (sponsor_id/site_id in the body) is rejected with 422 — proving
    # the SERVER owns tenancy, not the client or the model tool. Reuses INV-004's
    # body-tenancy expectation; this is the behavioral half of INV-012a, distinct
    # from the structural route-table checks above.
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
        "sponsor_id": "a9000000-0000-4000-8000-0000000000ff",
        "site_id": "a9000000-0000-4000-8000-0000000000fe",
    }
    resp = client.post("/sessions", json=body)
    assert resp.status_code == 422, (
        "INV-012a: a client/model-supplied tenant scope must be rejected (422); "
        "the server, not the client, owns tenancy"
    )
