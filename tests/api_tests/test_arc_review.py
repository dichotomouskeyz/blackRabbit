"""Spec ARC read contract: persisted reports, both tenant dimensions, no execution."""

import hashlib
import json
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import psycopg2
import pytest
from psycopg2.extras import Json

from api import arc, deps
from tests.api_tests.support import (
    _INT_PARTICIPANT,
    _INT_SITE_A,
    _INT_SPONSOR_A,
    _UNIT_VALID_SESSION_ID,
)


@pytest.fixture
def persisted_reports(db_conn, seeded_sessions):
    """Persist two reports and a newer wrong-site row to test scoped selection."""
    reports = []
    for index in range(3):
        analysis_id = str(uuid.uuid4())
        site = seeded_sessions["site_b" if index == 2 else "site_a"]
        artifact = {
            "analysis_id": analysis_id,
            "algorithm_version": "arc-test-v1",
            "config_sha256": "a" * 64,
            "input_sha256": "b" * 64,
            "identity": {
                "session_id": seeded_sessions["verified"],
                "participant_id": _INT_PARTICIPANT,
                "sponsor_id": seeded_sessions["sponsor_a"],
                "site_id": site,
            },
            "events": [],
            "quality_flags": ["synthetic_test_fixture"],
        }
        digest = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()
        created = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO analysis_runs "
                "(id, session_id, participant_id, sponsor_id, site_id, config_sha256, "
                "input_sha256, algorithm_version, artifact_sha256, artifact, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    analysis_id,
                    seeded_sessions["verified"],
                    _INT_PARTICIPANT,
                    seeded_sessions["sponsor_a"],
                    site,
                    "a" * 64,
                    "b" * 64,
                    "arc-test-v1",
                    digest,
                    Json(artifact),
                    created,
                ),
            )
        reports.append({"id": analysis_id, "artifact": artifact, "digest": digest})
    db_conn.commit()
    try:
        yield reports
    finally:
        db_conn.rollback()
        with db_conn.cursor() as cur:
            for report in reports:
                cur.execute("DELETE FROM analysis_runs WHERE id=%s", (report["id"],))
        db_conn.commit()


@pytest.mark.integration
def test_arc_returns_latest_scoped_persisted_artifact_without_execution(
    client, override_tenant, seeded_sessions, persisted_reports, db_conn, monkeypatch
):
    def no_execution(*args, **kwargs):
        raise AssertionError("ARC read attempted analysis execution")

    monkeypatch.setattr("batch.arc.processor.run_arc_post_session", no_execution)
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])

    def counts():
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT (SELECT count(*) FROM analysis_runs WHERE session_id=%s), "
                "(SELECT count(*) FROM audit_events WHERE session_id=%s), "
                "(SELECT status::text FROM sessions WHERE id=%s)",
                (seeded_sessions["verified"],) * 3,
            )
            return cur.fetchone()

    before = counts()
    response = client.get(f"/sessions/{seeded_sessions['verified']}/arc")
    assert response.status_code == 200, response.text
    body = response.json()
    expected = persisted_reports[1]
    assert set(body) == {"session_id", "analysis_id", "created_at", "provenance", "artifact"}
    assert body["session_id"] == seeded_sessions["verified"]
    assert body["analysis_id"] == expected["id"]
    assert body["artifact"] == expected["artifact"]
    assert body["provenance"] == {
        "algorithm_version": "arc-test-v1",
        "config_sha256": "a" * 64,
        "input_sha256": "b" * 64,
        "artifact_sha256": expected["digest"],
    }
    assert datetime.fromisoformat(body["created_at"]) == datetime(
        2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc
    )
    assert counts() == before


@pytest.mark.integration
def test_verified_session_without_analysis_has_defined_404(
    client, override_tenant, seeded_sessions
):
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    response = client.get(f"/sessions/{seeded_sessions['verified']}/arc")
    assert response.status_code == 404
    assert response.json()["error"] == "analysis_not_found"


@pytest.mark.integration
@pytest.mark.parametrize("state", ["notstarted", "inprogress", "failed"])
def test_arc_read_rejects_every_unverified_state(client, override_tenant, seeded_sessions, state):
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    response = client.get(f"/sessions/{seeded_sessions[state]}/arc")
    assert response.status_code == 409
    assert response.json()["error"] == "watermark_not_verified"


@pytest.mark.integration
@pytest.mark.parametrize("endpoint", ["status", "arc"])
@pytest.mark.parametrize("foreign_dimension", ["sponsor", "site"])
def test_reads_hide_sessions_outside_either_tenant_dimension(
    client, override_tenant, seeded_sessions, endpoint, foreign_dimension
):
    sponsor = seeded_sessions["sponsor_b" if foreign_dimension == "sponsor" else "sponsor_a"]
    site = seeded_sessions["site_b" if foreign_dimension == "site" else "site_a"]
    override_tenant(sponsor, site)
    response = client.get(f"/sessions/{seeded_sessions['verified']}/{endpoint}")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


@pytest.mark.integration
def test_list_excludes_same_sponsor_wrong_site(client, override_tenant, seeded_sessions):
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_b"])
    response = client.get("/sessions")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["sessions"]}
    for key in ("verified", "notstarted", "inprogress", "failed", "other_sponsor"):
        assert seeded_sessions[key] not in ids


@pytest.mark.integration
def test_unknown_arc_session_is_404(client, override_tenant, seeded_sessions):
    override_tenant(seeded_sessions["sponsor_a"], seeded_sessions["site_a"])
    response = client.get(f"/sessions/{uuid.uuid4()}/arc")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_invalid_arc_uuid_fails_before_database(client, monkeypatch):
    def no_connection():
        raise AssertionError("Invalid UUID reached database")

    monkeypatch.setattr(deps, "get_readonly_connection", no_connection)
    response = client.get("/sessions/not-a-uuid/arc")
    assert response.status_code == 422
    assert response.json()["field"] == "session_id"


@pytest.mark.parametrize("missing", ["sponsor", "site"])
def test_arc_requires_both_server_tenant_values(client, override_tenant, monkeypatch, missing):
    def no_connection():
        raise AssertionError("Missing tenancy reached database")

    monkeypatch.setattr(deps, "get_readonly_connection", no_connection)
    override_tenant(
        "" if missing == "sponsor" else _INT_SPONSOR_A,
        "" if missing == "site" else _INT_SITE_A,
    )
    response = client.get(f"/sessions/{_UNIT_VALID_SESSION_ID}/arc")
    assert response.status_code == 503
    assert response.json()["error"] == "tenancy_not_configured"


def test_arc_database_unavailable_returns_503(client, override_tenant, monkeypatch):
    def unavailable():
        raise psycopg2.OperationalError("unavailable")

    override_tenant(_INT_SPONSOR_A, _INT_SITE_A)
    monkeypatch.setattr(deps, "get_readonly_connection", unavailable)
    response = client.get(f"/sessions/{_UNIT_VALID_SESSION_ID}/arc")
    assert response.status_code == 503
    assert response.json()["error"] == "backend_unavailable"


@pytest.mark.parametrize("status, expected", [("failed", "failed"), ("active", "in_progress")])
def test_historical_verification_cannot_override_current_lifecycle(status, expected):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (status,)
    cur.fetchall.return_value = [("watermark_verified",)]
    with pytest.raises(arc.WatermarkNotVerified) as error:
        arc.assert_session_arc_ready(conn, _UNIT_VALID_SESSION_ID, _INT_SPONSOR_A, _INT_SITE_A)
    assert error.value.watermark_state == expected


@pytest.mark.integration
def test_api_reads_use_readonly_consistent_snapshot(readonly_url):
    with closing(deps.get_readonly_connection()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege(current_user, 'analysis_runs', 'SELECT'), "
            "has_table_privilege(current_user, 'analysis_runs', 'INSERT'), "
            "has_table_privilege(current_user, 'analysis_runs', 'UPDATE'), "
            "has_table_privilege(current_user, 'analysis_runs', 'DELETE')"
        )
        assert cur.fetchone() == (True, False, False, False)
        cur.execute("SHOW transaction_isolation")
        assert cur.fetchone()[0] == "repeatable read"


def test_arc_openapi_has_closed_envelope_and_provenance(app):
    schema = app.openapi()
    response = schema["paths"]["/sessions/{session_id}/arc"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith("ARCReviewResponse")
    for model in ("ARCReviewResponse", "ARCProvenance"):
        assert schema["components"]["schemas"][model]["additionalProperties"] is False
