"""INV-001 (QA-004) — None-tenancy fails closed with a clear 503, no DB call.

When `API_SPONSOR_ID`/`API_SITE_ID` are unset, `api.deps.get_tenant_context`
raises `ConfigurationError`, mapped by an app handler to
`503 {"error":"tenancy_not_configured", ...}` BEFORE any DB connection is opened
or any wrapped contract is called — so no tenancy-scoped route ever runs with
`sponsor_id=None` (fail-closed). The UI vars stay optional in
`settings.validate()` (INV-015); only the request fails.

These tests deliberately do NOT use `override_tenant`: they drive the real
None-tenancy resolution path.
"""

import pytest

from config import settings
from tests.api_tests.support import (
    _INT_PARTICIPANT,
    _UNIT_VALID_COMPOUND,
    _UNIT_VALID_SESSION_ID,
)


@pytest.fixture
def _none_tenancy(monkeypatch):
    """Unset server tenancy and trip-wire every DB entry point.

    Any DB connection during a None-tenancy request is a fail-closed violation,
    so both the API read factory and psycopg2.connect raise AssertionError if
    reached.
    """
    monkeypatch.setattr(settings, "API_SPONSOR_ID", None)
    monkeypatch.setattr(settings, "API_SITE_ID", None)

    def _no_db(*a, **k):
        raise AssertionError("None-tenancy request reached a DB connection")

    monkeypatch.setattr("api.deps.get_readonly_connection", _no_db)
    monkeypatch.setattr("psycopg2.connect", _no_db)


def _assert_tenancy_not_configured(resp):
    assert resp.status_code == 503, (
        f"None-tenancy must fail closed with 503, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("error") == "tenancy_not_configured", body
    assert "message" in body and body["message"], body


def test_get_sessions_none_tenancy_returns_503_no_db(client, _none_tenancy):
    resp = client.get("/sessions")
    _assert_tenancy_not_configured(resp)


def test_get_session_status_none_tenancy_returns_503_no_db(client, _none_tenancy):
    resp = client.get(f"/sessions/{_UNIT_VALID_SESSION_ID}/status")
    _assert_tenancy_not_configured(resp)


def test_post_sessions_none_tenancy_returns_503_no_db(client, _none_tenancy):
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
    }
    resp = client.post("/sessions", json=body)
    _assert_tenancy_not_configured(resp)


def test_settings_validate_unaffected_by_unset_tenancy(monkeypatch):
    # INV-015: tenancy vars unset must NOT break settings.validate().
    monkeypatch.setattr(settings, "API_SPONSOR_ID", None)
    monkeypatch.setattr(settings, "API_SITE_ID", None)
    # Must not raise.
    settings.validate()
