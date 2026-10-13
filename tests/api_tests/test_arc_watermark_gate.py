"""INV-006 — ARC endpoints gate on an explicit watermark check in api/ first.

B1 fix: the ARC endpoints are capability-gated (409) in M0, so the watermark
gate is NOT reachable through the HTTP surface — a spy-on-the-definition-module
test was vacuous (the gate never runs, so "ARC not entered" is trivially true).

INV-006 is instead made testable now by extracting the gate as a directly
callable function, `api.arc.assert_session_arc_ready(conn, session_id,
sponsor_id)`, and exercising IT against the real DB via the `seeded_sessions`
fixture (four watermark states). The function must:
  - RAISE for not_started / in_progress / failed (gate closed), and
  - RETURN / pass for verified (positive case proving the gate reads the DB).

The watermark states are genuinely DERIVED: the seed fixture drives real
sessions status transitions (active->closed, active->failed) so migration
`024_watermark_trigger` writes the `watermark_verified` / `watermark_failed`
audit events the gate reads — they are not asserted into existence.

This holds in M0 (gate independent of the capability stub) and post-unblock.
Marked integration since the watermark state is derived from seeded DB rows.
"""

import pytest

# --- B1 load-bearing: the gate function read against the real DB --------------


@pytest.mark.integration
@pytest.mark.parametrize("fixture_key", ["notstarted", "inprogress", "failed"])
def test_arc_gate_raises_for_non_verified(db_conn, seeded_sessions, fixture_key):
    # Tests INV-006 [integration]: the gate RAISES for every non-verified state,
    # reading sessions.status + watermark audit events from the real DB.
    from api.arc import assert_session_arc_ready

    with pytest.raises(Exception) as exc_info:
        assert_session_arc_ready(
            db_conn, seeded_sessions[fixture_key], seeded_sessions["sponsor_a"]
        )
    # The gate must signal a capability/watermark refusal, not an arbitrary error
    # (e.g. a NotImplementedError leaking from a stub). It must name the gate
    # concept so the HTTP layer can map it to the 409 capability-status body.
    name = type(exc_info.value).__name__
    assert name in ("WatermarkNotVerified", "CapabilityUnavailable"), (
        f"INV-006: gate must raise a watermark/capability refusal, got {name}: {exc_info.value!r}"
    )


@pytest.mark.integration
def test_arc_gate_passes_for_verified(db_conn, seeded_sessions):
    # Tests INV-006 [integration]: positive case — a genuinely watermark_verified
    # session (active->closed transition fired the 024 trigger) passes the gate.
    # This proves the gate actually reads the DB, not that it blanket-refuses.
    from api.arc import assert_session_arc_ready

    # Must NOT raise for the verified session.
    assert_session_arc_ready(
        db_conn, seeded_sessions["verified"], seeded_sessions["sponsor_a"]
    ) is None or True


@pytest.mark.integration
def test_arc_gate_derives_state_from_trigger_events(db_conn, seeded_sessions):
    # Tests INV-006 [integration]: confirm the seed actually fired the 024
    # watermark trigger, so watermark_state is DERIVED, not asserted into being.
    # verified-session -> watermark_verified event; failed-session ->
    # watermark_failed event. If this fails, the gate test above is not testing a
    # real derived state.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT event_type FROM audit_events "
            "WHERE session_id = %(id)s::uuid AND event_type = 'watermark_verified'",
            {"id": seeded_sessions["verified"]},
        )
        assert cur.fetchone() is not None, (
            "seed did not fire watermark_verified for the verified session "
            "(active->closed must trip the 024 trigger)"
        )
        cur.execute(
            "SELECT event_type FROM audit_events "
            "WHERE session_id = %(id)s::uuid AND event_type = 'watermark_failed'",
            {"id": seeded_sessions["failed"]},
        )
        assert cur.fetchone() is not None, (
            "seed did not fire watermark_failed for the failed session "
            "(active->failed must trip the 024 trigger)"
        )
        # not_started / in_progress must have NO terminal watermark event.
        for key, _ in (("notstarted", None), ("inprogress", None)):
            cur.execute(
                "SELECT 1 FROM audit_events WHERE session_id = %(id)s::uuid "
                "AND event_type IN ('watermark_verified', 'watermark_failed')",
                {"id": seeded_sessions[key]},
            )
            assert cur.fetchone() is None, f"{key} session must have no terminal watermark event"


# --- M0 HTTP-surface check: ARC endpoints still 409 via capability gate -------
# These remain valid in M0 (capability gate) and document that the HTTP path
# never reaches the watermark gate yet. The ARC-not-entered assertion is the
# capability gate's job; the watermark gate itself is covered above.


@pytest.mark.integration
def test_arc_read_on_unverified_session_returns_409(client, override_tenant, seeded_sessions):
    # Tests INV-006 [integration]: GET arc on in_progress session -> 409 (M0
    # capability gate; watermark gate not yet reached through HTTP).
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    resp = client.get(f"/sessions/{seeded_sessions['inprogress']}/arc")
    assert resp.status_code == 409


@pytest.mark.integration
def test_arc_run_on_failed_session_returns_409(client, override_tenant, seeded_sessions):
    # Tests INV-006 / PRH-004 [integration]: arc:run on failed session -> 409.
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    resp = client.post(f"/sessions/{seeded_sessions['failed']}/arc:run")
    assert resp.status_code == 409
