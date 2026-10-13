"""INV-016 — GET /sessions/{id}/status returns watermark_state enum.

watermark_state is one of not_started|in_progress|verified|failed, derived from
sessions.status + watermark audit events. Sessions are seeded in each state.
"""

import pytest

_VALID_STATES = {"not_started", "in_progress", "verified", "failed"}


@pytest.mark.integration
@pytest.mark.parametrize(
    "fixture_key,expected_state",
    [
        ("verified", "verified"),
        ("inprogress", "in_progress"),
        ("failed", "failed"),
        ("notstarted", "not_started"),
    ],
)
def test_status_returns_derived_watermark_state(
    client, override_tenant, seeded_sessions, fixture_key, expected_state
):
    # Tests INV-016 [integration]: watermark_state derived from status + audit events.
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    resp = client.get(f"/sessions/{seeded_sessions[fixture_key]}/status")
    assert resp.status_code == 200, f"status failed: {resp.status_code} {resp.text}"
    payload = resp.json()
    assert payload["watermark_state"] in _VALID_STATES, (
        f"watermark_state must be a closed enum, got {payload.get('watermark_state')!r}"
    )
    assert payload["watermark_state"] == expected_state, (
        f"{fixture_key}: expected watermark_state {expected_state}, "
        f"got {payload['watermark_state']}"
    )


@pytest.mark.integration
def test_status_does_not_return_boolean_pair(client, override_tenant, seeded_sessions):
    # Tests INV-016 [integration]: never an ambiguous {verified, failed} bool pair.
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    payload = client.get(f"/sessions/{seeded_sessions['verified']}/status").json()
    assert "verified" not in payload, "must not expose a raw `verified` boolean"
    assert "failed" not in payload, "must not expose a raw `failed` boolean"
    assert "watermark_state" in payload
