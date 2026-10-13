"""Persisted analysis provenance contract in db/SCHEMA.md (027 and 028)."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "table,required",
    [
        ("analysis_runs", {"artifact", "artifact_sha256", "input_sha256", "config_sha256"}),
        ("session_baselines", {"analysis_id", "epoch_count", "units", "extractor_version"}),
        ("event_composite_profiles", {"analysis_id", "echo_event_id", "fdr_q_value"}),
    ],
)
def test_saved_reports_have_required_provenance(cursor, table, required):
    cursor.execute(
        "SELECT column_name, is_nullable FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    columns = dict(cursor.fetchall())
    assert required <= columns.keys()
    assert all(columns[column] == "NO" for column in required)


@pytest.mark.parametrize("table", ["session_baselines", "event_composite_profiles"])
def test_derived_rows_reference_the_saved_analysis(cursor, table):
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid=%s::regclass AND contype='f'",
        (table,),
    )
    assert any(
        "FOREIGN KEY (analysis_id) REFERENCES analysis_runs(id)" in definition
        for (definition,) in cursor.fetchall()
    )


def test_baseline_identity_preserves_multiple_analysis_runs(cursor):
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='session_baselines'::regclass AND contype='p'"
    )
    assert cursor.fetchone()[0] == "PRIMARY KEY (analysis_id, modality, signal_component)"
