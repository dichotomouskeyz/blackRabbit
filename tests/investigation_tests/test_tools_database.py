"""RI-002/003/006: real database roles, query shapes and read-only provenance."""

import copy
import os
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from batch.arc.storage import persist_analysis
from investigation.models import InvestigationError
from investigation.tools import RecordingTools


@pytest.fixture
def recording_database(db_conn):
    identity = {
        key: str(uuid4()) for key in ("session_id", "participant_id", "site_id", "sponsor_id")
    }
    device = str(uuid4())
    keys = (
        identity["session_id"],
        identity["participant_id"],
        identity["site_id"],
        identity["sponsor_id"],
    )
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions(id,participant_id,site_id,sponsor_id,compound,status) "
            "VALUES(%s,%s,%s,%s,'psilocybin','active')",
            keys,
        )
        cur.execute(
            "INSERT INTO session_signal_metadata(session_id,participant_id,site_id,sponsor_id,"
            "device_id,modality,sample_rate_hz) VALUES(%s,%s,%s,%s,%s,'eda',1)",
            (*keys, device),
        )
        cur.execute(
            "INSERT INTO eda_samples(session_id,participant_id,site_id,sponsor_id,device_id,"
            "lsl_timestamp,sample_index,raw_conductance_us,conductance_us,sqi_flag) "
            "SELECT %s,%s,%s,%s,%s,t,t,2,2,CASE WHEN t=12 THEN 1 ELSE 0 END "
            "FROM generate_series(0,49) t",
            (*keys, device),
        )
        cur.execute(
            "INSERT INTO echo_events(session_id,participant_id,site_id,sponsor_id,event_type,"
            "source,actor_role,zone_label,lsl_timestamp) VALUES(%s,%s,%s,%s,'manual_marker',"
            "'manual_logging','therapist','participant_note',10) RETURNING id",
            keys,
        )
        event_id = cur.fetchone()[0]
        cur.execute("UPDATE sessions SET status='closed',closed_at=NOW() WHERE id=%s", (keys[0],))
    artifact = dict(
        identity=identity,
        analysis_id=str(uuid4()),
        algorithm_version="investigation-test",
        config_sha256="a" * 64,
        input_sha256="b" * 64,
        config={"features": {"epoch_s": 10}},
        events=[
            dict(
                echo_event_id=event_id,
                testable=False,
                test_exclusion_reason="test_fixture",
                p_value=1.0,
                fdr_q_value=1.0,
                windows={},
            )
        ],
        baseline=[],
        quality_summary={"eda": {"sample_count": 50, "flagged_sample_count": 1}},
        unavailable_signals={},
        limitations=["Synthetic fixture"],
    )
    persist_analysis(db_conn, artifact, [], [])
    db_conn.commit()
    try:
        yield identity, artifact, db_conn
    finally:
        db_conn.rollback()
        with db_conn.cursor() as cur:
            for table in ("eda_samples", "session_signal_metadata", "analysis_runs", "echo_events"):
                cur.execute(
                    sql.SQL("DELETE FROM {} WHERE session_id=%s").format(sql.Identifier(table)),
                    (keys[0],),
                )
            cur.execute("DELETE FROM sessions WHERE id=%s", (keys[0],))
        db_conn.commit()


@pytest.mark.integration
def test_ri002_readonly_tools_do_not_mutate_recording_and_pin_analysis(recording_database):
    readonly_url = os.environ.get("API_READONLY_DATABASE_URL")
    if not readonly_url:
        pytest.skip("API_READONLY_DATABASE_URL is needed for role verification")
    identity, artifact, conn = recording_database
    scope = {key: identity[key] for key in ("session_id", "sponsor_id", "site_id")}
    with psycopg2.connect(readonly_url) as readonly, readonly.cursor() as cur:
        cur.execute("SELECT has_table_privilege(current_user,'eda_samples','INSERT')")
        assert cur.fetchone()[0] is False
    tools = RecordingTools(**scope, connect=lambda: psycopg2.connect(readonly_url))
    pinned = tools.analysis_id
    event_id = artifact["events"][0]["echo_event_id"]
    before = artifact.copy()
    assert tools.list_events()["events"][0]["event_id"] == event_id
    assert tools.get_session_summary()["capture_source"] == "simulated"
    assert tools.get_recording_quality()["quality_summary"]["eda"]["flagged_sample_count"] == 1
    assert len(tools.list_sessions()["sessions"]) == 1
    result = tools.inspect_signal_window("eda", 0, 50)
    assert result["statistics"]["eda"]["usable_sample_count"] == 49
    assert result["statistics"]["eda"]["mean"] == 2.0
    newer = copy.deepcopy(artifact)
    newer["analysis_id"] = str(uuid4())
    newer["events"][0]["p_value"] = 0.5
    persist_analysis(conn, newer, [], [])
    conn.commit()
    assert tools.get_event_response(event_id)["response"]["p_value"] == 1.0
    assert tools.analysis_id == pinned
    with conn.cursor() as cur:
        cur.execute("SELECT artifact FROM analysis_runs WHERE id=%s", (pinned,))
        assert cur.fetchone()[0] == before
        cur.execute("SELECT count(*) FROM eda_samples WHERE session_id=%s", (scope["session_id"],))
        assert cur.fetchone()[0] == 50
    for dimension in ("sponsor_id", "site_id"):
        with pytest.raises(InvestigationError) as raised:
            RecordingTools(
                **{**scope, dimension: str(uuid4())}, connect=lambda: psycopg2.connect(readonly_url)
            )
        assert raised.value.status_code == 404
