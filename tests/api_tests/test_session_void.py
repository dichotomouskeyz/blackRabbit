"""session-void SV-001..SV-006 — void a closed or failed session.

Unit tests cover input validation (no database), error mapping and the SQL
constants. Integration tests void seeded sessions and check status, list
visibility, the audit trail, ARC refusal and the schema constraint.
"""

import psycopg2
import pytest

import capture.session_void as session_void
from api import capabilities
from tests.api_tests.support import WRITE_TOKEN_RE

_REASON = "Electrode impedance out of range for the whole recording"


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(
        "psycopg2.connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("invalid input reached the DB")),
    )


# --- SV-004: validation before the database ---------------------------------


@pytest.mark.parametrize("reason", [None, "", "  ", "ab", "x" * 501, 42])
def test_reason_bounds(reason):
    with pytest.raises(ValueError):
        session_void.clean_reason(reason)


def test_reason_is_trimmed():
    assert session_void.clean_reason("  bad leads  ") == "bad leads"


@pytest.mark.parametrize(
    ("path_id", "body", "field"),
    [
        ("not-a-uuid", {"reason": _REASON}, "session_id"),
        ("a9000000-0000-4000-8000-00000000ffff", {}, "reason"),
        ("a9000000-0000-4000-8000-00000000ffff", {"reason": "no"}, "reason"),
        ("a9000000-0000-4000-8000-00000000ffff", {"reason": "x" * 501}, "reason"),
    ],
)
def test_api_rejects_bad_input_before_db(client, no_db, path_id, body, field):
    resp = client.post(f"/sessions/{path_id}/void", json=body)
    assert resp.status_code == 422
    assert resp.json()["field"] == field


def test_api_rejects_extra_body_fields(client, no_db):
    resp = client.post(
        "/sessions/a9000000-0000-4000-8000-00000000ffff/void",
        json={"reason": _REASON, "sponsor_id": "a9000000-0000-4000-8000-0000000000b1"},
    )
    assert resp.status_code == 422


# --- error mapping (domain stubbed) -----------------------------------------


@pytest.mark.parametrize(
    ("raised", "status_code", "error"),
    [
        (session_void.SessionNotFound("x"), 404, "not_found"),
        (session_void.SessionAlreadyVoided("x"), 409, "already_voided"),
        (session_void.SessionNotVoidable("active"), 409, "session_not_voidable"),
        (session_void.SessionBusy("x"), 409, "session_busy"),
    ],
)
def test_domain_errors_map_to_responses(
    client, override_tenant, monkeypatch, raised, status_code, error
):
    def _raise(**_kwargs):
        raise raised

    monkeypatch.setattr(session_void, "void_session", _raise)
    override_tenant("a9000000-0000-4000-8000-0000000000a1", "a9000000-0000-4000-8000-0000000000a2")
    resp = client.post(
        "/sessions/a9000000-0000-4000-8000-00000000ffff/void", json={"reason": _REASON}
    )
    assert resp.status_code == status_code
    assert resp.json()["error"] == error


def test_capability_row_is_implemented():
    rows = {r["capability"]: r for r in capabilities.CAPABILITY_MATRIX}
    assert rows["void_session"]["status"] == "implemented"
    assert rows["void_session"]["endpoint"] == "POST /sessions/{id}/void"


def test_void_sql_is_scoped_and_never_deletes():
    sql = session_void._VOID_SQL
    assert sql.startswith("UPDATE sessions SET status = 'voided'")
    for scope in ("%(session_id)s", "%(sponsor_id)s", "%(site_id)s"):
        assert scope in sql
    assert "status IN ('closed', 'failed')" in sql
    tokens = {m.group(1).upper() for m in WRITE_TOKEN_RE.finditer(sql)}
    assert tokens == {"UPDATE"}, f"void must only UPDATE, found {tokens}"


# --- SV-001..SV-006 against the database ------------------------------------


@pytest.fixture
def scoped(client, override_tenant, seeded_sessions):
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    return client


def _void(client, session_id, reason=_REASON):
    return client.post(f"/sessions/{session_id}/void", json={"reason": reason})


@pytest.mark.integration
def test_void_closed_session(scoped, seeded_sessions, cursor):
    sid = seeded_sessions["verified"]
    resp = _void(scoped, sid)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "voided"

    status = scoped.get(f"/sessions/{sid}/status").json()
    assert status["status"] == "voided"
    assert status["watermark_state"] == "verified", "watermark reports the replaced lifecycle"

    cursor.execute(
        "SELECT voided_from::text, void_reason FROM sessions WHERE id = %s::uuid", (sid,)
    )
    assert cursor.fetchone() == ("closed", _REASON)


@pytest.mark.integration
def test_voided_sessions_leave_the_default_list(scoped, seeded_sessions):
    sid = seeded_sessions["failed"]
    assert _void(scoped, sid).status_code == 200
    default_ids = {s["id"] for s in scoped.get("/sessions").json()["sessions"]}
    assert sid not in default_ids
    voided_ids = {s["id"] for s in scoped.get("/sessions?status=voided").json()["sessions"]}
    assert sid in voided_ids


@pytest.mark.integration
def test_void_is_audited_by_the_trigger(scoped, seeded_sessions, cursor):
    sid = seeded_sessions["verified"]
    assert _void(scoped, sid).status_code == 200
    cursor.execute(
        "SELECT payload->>'old_status', payload->>'new_status' FROM audit_events "
        "WHERE session_id = %s::uuid AND event_type = 'session_status_transition' "
        "ORDER BY event_timestamp DESC, id DESC LIMIT 1",
        (sid,),
    )
    assert cursor.fetchone() == ("closed", "voided")


@pytest.mark.integration
def test_active_session_is_not_voidable(scoped, seeded_sessions):
    resp = _void(scoped, seeded_sessions["inprogress"])
    assert resp.status_code == 409
    assert resp.json() == {
        "error": "session_not_voidable",
        "message": "only closed or failed sessions can be voided; end capture first",
        "status": "active",
    }


@pytest.mark.integration
def test_second_void_conflicts(scoped, seeded_sessions):
    sid = seeded_sessions["verified"]
    assert _void(scoped, sid).status_code == 200
    resp = _void(scoped, sid)
    assert resp.status_code == 409
    assert resp.json()["error"] == "already_voided"


@pytest.mark.integration
def test_other_sponsor_session_is_not_found(scoped, seeded_sessions):
    assert _void(scoped, seeded_sessions["other_sponsor"]).status_code == 404


@pytest.mark.integration
def test_arc_read_refuses_a_voided_session(scoped, seeded_sessions):
    sid = seeded_sessions["verified"]
    assert _void(scoped, sid).status_code == 200
    resp = scoped.get(f"/sessions/{sid}/arc")
    assert resp.status_code == 409
    assert resp.json()["error"] == "session_voided"


@pytest.mark.integration
def test_schema_requires_a_void_record(seeded_sessions, cursor, db_conn):
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            "UPDATE sessions SET status = 'voided' WHERE id = %s::uuid",
            (seeded_sessions["verified"],),
        )
    db_conn.rollback()
