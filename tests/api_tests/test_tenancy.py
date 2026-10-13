"""INV-001 — tenancy server-injected; reads filter by server sponsor_id.

- GET /sessions and /sessions/{id}/status filter by the server-injected
  sponsor_id; a session under a different sponsor is NOT returned.
- POST /sessions body-supplied sponsor_id/site_id never reaches the created row
  (server tenancy wins).

Two sponsors are seeded; the test overrides EA-003's single-sponsor default via
the deps tenant-context override.
"""

import pytest

from tests.api_tests.support import _INT_PARTICIPANT, _UNIT_VALID_COMPOUND


@pytest.mark.integration
def test_list_sessions_filters_by_server_sponsor(client, override_tenant, seeded_sessions):
    # Tests INV-001 [integration]: list excludes other-sponsor sessions.
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    resp = client.get("/sessions")
    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()["sessions"]}
    assert seeded_sessions["verified"] in ids, "sponsor A's own session must be listed"
    assert seeded_sessions["other_sponsor"] not in ids, (
        "INV-001: a session under a different sponsor must not be returned"
    )


@pytest.mark.integration
def test_status_filters_by_server_sponsor(client, override_tenant, seeded_sessions):
    # Tests INV-001 [integration]: status for another sponsor's session is not exposed.
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    resp = client.get(f"/sessions/{seeded_sessions['other_sponsor']}/status")
    assert resp.status_code == 404, (
        "INV-001: a cross-sponsor session must be 404 (not visible), not 200"
    )


@pytest.mark.integration
def test_post_body_sponsor_never_reaches_row(client, override_tenant, seeded_sessions, cursor):
    # Tests INV-001 [integration]: even if a body sneaks tenancy through, the row
    # carries the SERVER sponsor/site, never the client-supplied values.
    server_sponsor = seeded_sessions["sponsor_a"]
    server_site = seeded_sessions["site_a"]
    override_tenant(server_sponsor, server_site)
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": _INT_PARTICIPANT,
        "capture_source": "simulated",
    }
    resp = client.post("/sessions", json=body)
    assert resp.status_code in (200, 201), f"create failed: {resp.status_code} {resp.text}"
    session_id = resp.json()["session_id"]
    cursor.execute(
        "SELECT sponsor_id::text, site_id::text FROM sessions WHERE id = %s::uuid",
        (session_id,),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == server_sponsor, "row sponsor_id must be the server-injected value"
    assert row[1] == server_site, "row site_id must be the server-injected value"
    cursor.execute("DELETE FROM sessions WHERE id = %s::uuid", (session_id,))


@pytest.mark.integration
def test_create_session_never_called_with_none_sponsor(client, override_tenant, monkeypatch):
    # Tests INV-001 [integration]: no wrapped contract is called with sponsor_id=None.
    import capture.session_init.workflow as wf

    seen = []
    orig = wf.create_session

    def _spy(*args, **kwargs):
        seen.append(kwargs)
        return orig(*args, **kwargs)

    monkeypatch.setattr(wf, "create_session", _spy)
    override_tenant("a9000000-0000-4000-8000-0000000000a1", "a9000000-0000-4000-8000-0000000000a2")
    client.post(
        "/sessions",
        json={
            "compound": _UNIT_VALID_COMPOUND,
            "participant_id": _INT_PARTICIPANT,
            "capture_source": "simulated",
        },
    )
    assert seen, "create_session was not invoked by POST /sessions"
    for kwargs in seen:
        assert kwargs.get("sponsor_id") is not None, (
            "INV-001: create_session must never be called with sponsor_id=None"
        )
