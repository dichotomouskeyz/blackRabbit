"""session-query SQ-001..SQ-004 — optional filters on GET /sessions.

Unit tests cover validation (no database) and the SQL constant; integration
tests run the filters against seeded sessions under sponsor scope.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from api import session_filters, sessions
from api.session_filters import FilterError, parse_session_filters
from capture.session_init.constants import VALID_COMPOUNDS
from tests.api_tests.support import (
    _INT_PARTICIPANT,
    _INT_SESSION_FAILED,
    _INT_SESSION_INPROGRESS,
    _INT_SESSION_NOTSTARTED,
    _INT_SESSION_OTHER_SPONSOR,
    _INT_SESSION_VERIFIED,
    READ_PREFIX_RE,
    WRITE_TOKEN_RE,
)

_ROW_ALLOWLIST = {"id", "status", "compound", "started_at", "closed_at", "created_at"}
_SPONSOR_A_SESSIONS = {
    _INT_SESSION_VERIFIED,
    _INT_SESSION_INPROGRESS,
    _INT_SESSION_FAILED,
    _INT_SESSION_NOTSTARTED,
}


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(
        "psycopg2.connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("an invalid filter reached the DB")),
    )


# --- SQ-002: validation, no database ----------------------------------------


def test_no_filters_gives_defaults():
    f = parse_session_filters()
    assert f.as_params() == {
        "session_prefix": None,
        "participant_id": None,
        "status": None,
        "compound": None,
        "created_from": None,
        "created_before": None,
        "limit": session_filters.DEFAULT_LIMIT,
    }


def test_valid_filters_are_normalized():
    f = parse_session_filters(
        session_id="  9B2E41D0 ",
        participant_id=_INT_PARTICIPANT.upper(),
        status="closed",
        compound="psilocybin",
        created_from="2026-10-01",
        created_before="2026-10-13T08:00:00-07:00",
        limit="25",
    )
    assert f.session_prefix == "9b2e41d0"
    assert f.participant_id == _INT_PARTICIPANT
    assert f.created_from == datetime(2026, 10, 1, tzinfo=UTC)
    assert f.created_before == datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    assert f.limit == 25


def test_blank_values_do_not_filter():
    assert (
        parse_session_filters(session_id="", status="  ", created_from="")
        == parse_session_filters()
    )


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"session_id": "9b2e%"}, "session_id"),
        ({"session_id": "x" * 37}, "session_id"),
        ({"participant_id": "Jane Doe"}, "participant_id"),
        ({"created_from": "yesterday"}, "created_from"),
        ({"created_from": "2026-10-13T08:00:00"}, "created_from"),
        ({"created_from": "2026-10-13", "created_before": "2026-10-13"}, "created_before"),
        ({"limit": "0"}, "limit"),
        ({"limit": "501"}, "limit"),
        ({"limit": "ten"}, "limit"),
    ],
)
def test_invalid_filters_are_rejected(kwargs, field):
    with pytest.raises(FilterError) as exc:
        parse_session_filters(**kwargs)
    assert exc.value.field == field


def test_enum_errors_carry_valid_choices():
    with pytest.raises(FilterError) as status_exc:
        parse_session_filters(status="deleted")
    assert status_exc.value.valid_choices == list(session_filters.SESSION_STATUSES)
    with pytest.raises(FilterError) as compound_exc:
        parse_session_filters(compound="saline")
    assert compound_exc.value.valid_choices == list(VALID_COMPOUNDS)


@pytest.mark.parametrize(
    "query",
    [
        "participant_id=not-a-uuid",
        "status=deleted",
        "created_from=2026-13-40",
        "session_id=%27%3B%20DROP%20TABLE%20sessions%3B--",
        "limit=100000",
    ],
)
def test_api_returns_structured_422_before_db(client, no_db, query):
    resp = client.get(f"/sessions?{query}")
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) <= {"field", "message", "valid_choices"}
    assert body["field"] in {"participant_id", "status", "created_from", "session_id", "limit"}


# --- SQ-003: the SQL stays a parameterized read constant --------------------


def test_list_sql_is_parameterized_read():
    sql = sessions.SESSIONS_LIST_SQL
    assert READ_PREFIX_RE.match(sql)
    assert not WRITE_TOKEN_RE.search(sql)
    for name in parse_session_filters().as_params():
        assert f"%({name})s" in sql, f"{name} must be a bound parameter"


# --- SQ-001 / SQ-004: filters against seeded sessions ------------------------


def _ids(resp):
    assert resp.status_code == 200, resp.text
    rows = resp.json()["sessions"]
    for row in rows:
        assert set(row) == _ROW_ALLOWLIST, "SQ-004: response fields must not change"
    return {row["id"] for row in rows}


@pytest.fixture
def scoped(client, override_tenant, seeded_sessions):
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    return client


@pytest.mark.integration
def test_unfiltered_list_is_sponsor_scoped(scoped):
    ids = _ids(scoped.get("/sessions"))
    assert _SPONSOR_A_SESSIONS <= ids
    assert _INT_SESSION_OTHER_SPONSOR not in ids


@pytest.mark.integration
def test_filter_by_status(scoped):
    assert _ids(scoped.get("/sessions?status=closed")) & _SPONSOR_A_SESSIONS == {
        _INT_SESSION_VERIFIED
    }
    assert _ids(scoped.get("/sessions?status=initializing")) & _SPONSOR_A_SESSIONS == {
        _INT_SESSION_NOTSTARTED
    }


@pytest.mark.integration
def test_filter_by_session_id_prefix(scoped):
    assert _ids(scoped.get(f"/sessions?session_id={_INT_SESSION_FAILED.upper()}")) == {
        _INT_SESSION_FAILED
    }
    # The other sponsor's session shares the prefix but stays out of scope.
    assert _INT_SESSION_OTHER_SPONSOR not in _ids(scoped.get("/sessions?session_id=a9000000"))


@pytest.mark.integration
def test_filter_by_participant_never_returns_it(scoped):
    assert _SPONSOR_A_SESSIONS <= _ids(scoped.get(f"/sessions?participant_id={_INT_PARTICIPANT}"))
    assert _ids(scoped.get(f"/sessions?participant_id={uuid.uuid4()}")) == set()


@pytest.mark.integration
def test_filter_by_compound(scoped):
    assert _SPONSOR_A_SESSIONS <= _ids(scoped.get("/sessions?compound=psilocybin"))
    assert _ids(scoped.get("/sessions?compound=mdma")) & _SPONSOR_A_SESSIONS == set()


@pytest.mark.integration
def test_filter_by_created_range(scoped):
    now = datetime.now(UTC)
    window = {
        "created_from": (now - timedelta(days=1)).isoformat(),
        "created_before": (now + timedelta(days=1)).isoformat(),
    }
    assert _SPONSOR_A_SESSIONS <= _ids(scoped.get("/sessions", params=window))
    future = {"created_from": (now + timedelta(days=1)).isoformat()}
    assert _ids(scoped.get("/sessions", params=future)) == set()


@pytest.mark.integration
def test_limit_caps_rows(scoped):
    assert len(_ids(scoped.get("/sessions?limit=2"))) == 2
