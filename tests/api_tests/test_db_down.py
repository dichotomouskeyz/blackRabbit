"""INV-014 / BND-004 (QA-001) — DB-down maps to 503, not 500.

Every DB-touching endpoint must surface `psycopg2.OperationalError` (DB
unreachable or connection-exhausted) as a structured `503`
`{"error":"backend_unavailable", "message":...}` — never a raw 500/stack.

- GET /sessions and GET /sessions/{id}/status read via
  `api.deps.get_readonly_connection`; patching it to raise OperationalError
  binds because the routes use module-attribute access (QA-005).
- POST /sessions creates via the wrapped contract, which connects with
  `psycopg2.connect`; patching that to raise OperationalError exercises the
  create path's DB-down outcome.

Tenancy is overridden to a real sponsor/site so the request reaches the DB path
(otherwise a None-tenancy request would 503 for a different reason — see
test_tenancy_not_configured.py).
"""

import psycopg2
import pytest

from tests.api_tests.support import (
    _INT_PARTICIPANT,
    _INT_SITE_A,
    _INT_SPONSOR_A,
    _UNIT_VALID_COMPOUND,
    _UNIT_VALID_SESSION_ID,
)


def _assert_backend_unavailable(resp):
    assert resp.status_code == 503, f"DB-down must map to 503, not {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("error") == "backend_unavailable", body
    assert "message" in body and body["message"], body


@pytest.fixture
def _down_readonly(monkeypatch):
    """Patch the API read factory to raise OperationalError (DB down)."""

    def _boom(*a, **k):
        raise psycopg2.OperationalError("could not connect to server")

    monkeypatch.setattr("api.deps.get_readonly_connection", _boom)


@pytest.fixture
def _down_connect(monkeypatch):
    """Patch psycopg2.connect (the create path) to raise OperationalError."""

    def _boom(*a, **k):
        raise psycopg2.OperationalError("could not connect to server")

    monkeypatch.setattr("psycopg2.connect", _boom)


def test_get_sessions_db_down_returns_503(client, override_tenant, _down_readonly):
    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    resp = client.get("/sessions")
    _assert_backend_unavailable(resp)


def test_get_session_status_db_down_returns_503(client, override_tenant, _down_readonly):
    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    resp = client.get(f"/sessions/{_UNIT_VALID_SESSION_ID}/status")
    _assert_backend_unavailable(resp)


def test_post_sessions_db_down_returns_503(client, override_tenant, _down_connect):
    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
    }
    resp = client.post("/sessions", json=body)
    _assert_backend_unavailable(resp)
