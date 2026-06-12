"""INV-004 / BND-001 — fail-closed validation, no DB call on bad input.

- malformed UUID in a path -> 422 with NO DB call (connection factory not called)
- POST /sessions with an unknown body key -> 422
- POST /sessions containing site_id/sponsor_id -> rejected/ignored (server tenancy wins)
- SQL-injection string in a path id -> rejected at validation (no DB call)

These target `implemented` endpoints (GET /sessions/{id}/status, POST /sessions),
so they are reached by validation rather than capability-gated.
"""

import pytest

from tests.api_tests.support import (
    _INT_PARTICIPANT,
    _UNIT_MALFORMED_SESSION_ID,
    _UNIT_SQLI_SESSION_ID,
    _UNIT_VALID_COMPOUND,
)


@pytest.fixture
def no_db(monkeypatch):
    """Fail loudly if any DB connection is opened during a fail-closed test."""
    calls = []

    def _boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("INV-004/BND-001: invalid input reached a DB connection")

    monkeypatch.setattr("psycopg2.connect", _boom)
    return calls


def test_malformed_uuid_path_returns_422_no_db(client, no_db):
    # Tests INV-004 [integration]: malformed path UUID -> 422, no DB call.
    resp = client.get(f"/sessions/{_UNIT_MALFORMED_SESSION_ID}/status")
    assert resp.status_code == 422, f"expected 422 for malformed UUID, got {resp.status_code}"
    assert no_db == [], "no DB connection may be opened for a malformed path id"


def test_sql_injection_path_id_rejected_no_db(client, no_db):
    # Tests INV-004 / PRH-003 [integration]: SQLi string in path id rejected at validation.
    resp = client.get(f"/sessions/{_UNIT_SQLI_SESSION_ID}/status")
    assert resp.status_code == 422
    assert no_db == [], "SQL-injection path id must be rejected before any DB call"


def test_post_sessions_unknown_key_returns_422(client, no_db):
    # Tests INV-004 / BND-001 [integration]: unknown body key -> 422 (closed allow-list).
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
        "totally_unknown_key": "x",  # not in the allow-list
    }
    resp = client.post("/sessions", json=body)
    assert resp.status_code == 422, (
        f"unknown body key must be rejected with 422, got {resp.status_code}"
    )
    assert no_db == [], "unknown-key body must not reach a DB connection"


def test_post_sessions_with_sponsor_id_in_body_rejected_or_ignored(client, no_db):
    # Tests INV-004 / INV-001 [integration]: body site_id/sponsor_id is rejected
    # (closed allow-list forbids them) — server tenancy wins, never client-supplied.
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
        "sponsor_id": "a9000000-0000-4000-8000-0000000000ff",
        "site_id": "a9000000-0000-4000-8000-0000000000fe",
    }
    resp = client.post("/sessions", json=body)
    # The closed allow-list (RS-004) forbids tenancy keys -> 422.
    assert resp.status_code == 422, (
        "body-supplied sponsor_id/site_id must be rejected by the closed allow-list"
    )
    assert no_db == [], "a tenancy-bearing body must not reach a DB connection"
