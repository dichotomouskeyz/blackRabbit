"""Tests derived from arc-batch-release.md B-001 through B-010."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from batch.arc.convergence import benjamini_hochberg, deviation, empirical_p, null_densities
from batch.arc.features import Sample, band_power, epoch_value, feature_series
from batch.arc.pipeline import analyze_recording
from batch.arc.processor import ARCPostSessionError, run_arc_post_session
from batch.arc.storage import canonical_json, require_verified_session
from config.arc_watchdog import load_arc_watchdog_config


def _config():
    return load_arc_watchdog_config()


def _recording():
    # Two measured modalities, with multiple feature epochs and one transient change.
    data = {"hrv": [], "eda": [], "eeg": [], "respiration": []}
    for t in range(900):
        data["hrv"].append(
            Sample(float(t), 900 + 10 * np.sin(t / 3) + (250 if 400 <= t < 430 else 0))
        )
        data["eda"].append(Sample(float(t), 3 + 0.1 * np.sin(t / 4) + (2 if 400 <= t < 430 else 0)))
    metadata = {"hrv": {}, "eda": {}}
    anchors = [
        SimpleNamespace(
            id=1, lsl_timestamp=400.0, event_type="manual_marker", zone_label="participant_note"
        )
    ]
    return data, metadata, anchors


def test_b003_band_power_has_correct_band_and_squared_units():
    times = np.arange(1000) / 100
    values = 2 * np.sin(2 * np.pi * 10 * times)
    assert band_power(values.tolist(), times.tolist(), (8, 13)) == pytest.approx(2, rel=0.002)
    assert band_power(values.tolist(), times.tolist(), (4, 8)) < 1e-7


def test_b003_rr_features_use_defined_units_and_no_mean_rr_proxy():
    samples = [Sample(float(i), value) for i, value in enumerate([800, 1000, 800, 1000])]
    assert epoch_value("hrv", "hrv_rmssd", samples) == pytest.approx(200)
    assert epoch_value("hrv", "hrv_sdnn", samples) == pytest.approx(
        np.std([800, 1000, 800, 1000], ddof=1)
    )
    assert epoch_value("hrv", "heart_rate_bpm", samples) == pytest.approx(67.5)


def test_b003_no_respiration_amplitude_inversion():
    samples = [Sample(0, 2), Sample(1, 4)]
    assert epoch_value("respiration", "respiration_rate", samples) is None
    assert epoch_value("respiration", "respiration_amplitude", samples) == 3


def test_b004_flagged_epochs_are_unavailable_and_raw_samples_unchanged():
    rows = [Sample(float(i), 2.0, flagged=i < 8) for i in range(20)]
    before = list(rows)
    features = feature_series("eda", rows, ["eda_mean"], origin=0, end=20, epoch_s=10)
    assert features[0].values == (None, 2.0)
    assert rows == before


def test_b003_irregular_eeg_rejected():
    with pytest.raises(ValueError, match="regularly"):
        band_power([1.0] * 10, [0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.5], (8, 13))


def test_b007_deviation_is_dimensionless_and_finite_for_flat_baseline():
    assert deviation(12, 10, 2) == 1
    assert deviation(0, 0, 0) == 0
    assert np.isfinite(deviation(2, 0, 0))


def test_b008_bh_reference_vector_preserves_input_order():
    # Published BH step-up definition, independent expected values.
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.002]) == pytest.approx([0.02, 0.04, 0.04, 0.008])
    assert benjamini_hochberg([1, 1, 1]) == [1, 1, 1]
    assert benjamini_hochberg([]) == []


def test_b008_bh_matches_scipy_when_available():
    scipy_stats = pytest.importorskip("scipy.stats")
    values = np.random.default_rng(42).uniform(size=100)
    assert benjamini_hochberg(values.tolist()) == pytest.approx(
        scipy_stats.false_discovery_control(values, method="bh")
    )


def test_b008_seeded_null_is_identical_and_p_never_zero():
    values = np.arange(30, dtype=float)
    series = {"eda.eda_mean": ("eda", values, 10.0, 3.0)}
    args = dict(permutations=100, seed=4, threshold=2, min_modalities=1)
    first = null_densities(series, [(3, 6), (6, 12)], **args)
    assert np.array_equal(first, null_densities(series, [(3, 6), (6, 12)], **args))
    assert empirical_p(11, first) == pytest.approx(1 / 101)


def test_b008_missing_surrogate_support_is_not_counted_as_null_zero():
    values = np.r_[np.arange(10, dtype=float), np.full(990, np.nan)]
    series = {"hrv.x": ("hrv", values, 0, 1), "eda.x": ("eda", values, 0, 1)}
    result = null_densities(
        series, [(0, 3)], permutations=1000, seed=3, threshold=2, min_modalities=2
    )
    assert np.count_nonzero(np.isfinite(result)) < 100
    assert np.count_nonzero(np.isnan(result)) > 900


def test_b004_b006_b009_pipeline_records_missing_and_successive_windows_replays():
    data, metadata, anchors = _recording()
    identity = dict(
        session_id="test", sponsor_id="sponsor", site_id="site", participant_id="person"
    )
    artifact, baselines, _ = analyze_recording(
        identity, data, metadata, anchors, _config(), "a" * 64
    )
    again = analyze_recording(identity, data, metadata, anchors, _config(), "a" * 64)[0]
    assert canonical_json(artifact) == canonical_json(again)
    windows = artifact["events"][0]["windows"]
    assert [(w["start_lsl_timestamp"], w["end_lsl_timestamp"]) for w in windows.values()] == [
        (400, 430),
        (430, 520),
        (520, 700),
    ]
    assert artifact["unavailable_signals"]["eeg"] == "missing_metadata_or_samples"
    assert {row["modality"] for row in baselines} == {"hrv", "eda"}
    assert all(row["config_sha256"] == _config().content_sha256 for row in baselines)
    assert all(row["units"] for row in baselines)


def test_b006_incomplete_event_windows_are_explicit():
    data, metadata, anchors = _recording()
    anchors[0].lsl_timestamp = 850
    artifact, _, _ = analyze_recording({}, data, metadata, anchors, _config(), "a" * 64)
    assert artifact["events"][0]["windows"]["w1"]["eligible"]
    assert not artifact["events"][0]["windows"]["w2"]["eligible"]
    assert not artifact["events"][0]["windows"]["w3"]["eligible"]


def test_b009_changed_inputs_change_analysis_identity():
    data, metadata, anchors = _recording()
    a = analyze_recording({}, data, metadata, anchors, _config(), "a" * 64)[0]
    b = analyze_recording({}, data, metadata, anchors, _config(), "b" * 64)[0]
    assert a["analysis_id"] != b["analysis_id"]


def test_b001_gate_refuses_missing_tenant_before_database_access():
    with pytest.raises(ValueError, match="required"):
        require_verified_session(None, "session", "", "site")


def test_b010_interpretation_only_cites_passing_event_metrics():
    data, metadata, anchors = _recording()
    artifact, _, _ = analyze_recording({}, data, metadata, anchors, _config(), "a" * 64)
    assert artifact["interpretation"]
    events = {event["echo_event_id"]: event for event in artifact["events"]}
    for claim in artifact["interpretation"]:
        event = events[claim["echo_event_id"]]
        assert event["passed_fdr"]
        metric = event["windows"][claim["window"]]["metrics"][claim["signal_component"]]
        assert metric[claim["metric"]] == claim["value"]


SESSION = "ac000000-0000-4000-8000-000000000001"
PARTICIPANT = "ac000000-0000-4000-8000-000000000002"
SITE = "ac000000-0000-4000-8000-000000000003"
SPONSOR = "ac000000-0000-4000-8000-000000000004"
DEVICE = "ac000000-0000-4000-8000-000000000005"


@pytest.fixture
def batch_session(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sessions(id,participant_id,site_id,sponsor_id,capture_source,
            compound,status,started_at)
            VALUES(%s,%s,%s,%s,'simulated','psilocybin','active',NOW())""",
            (SESSION, PARTICIPANT, SITE, SPONSOR),
        )
        for modality in ("hrv", "eda"):
            cur.execute(
                """INSERT INTO session_signal_metadata(session_id,participant_id,site_id,
                sponsor_id,device_id,capture_source,modality,sample_rate_hz)
                VALUES(%s,%s,%s,%s,%s,'simulated',%s,1)""",
                (SESSION, PARTICIPANT, SITE, SPONSOR, DEVICE, modality),
            )
        cur.execute(
            """INSERT INTO hrv_samples(id,session_id,participant_id,site_id,sponsor_id,
            device_id,lsl_timestamp,db_insert_time,sample_index,rr_interval_ms)
            SELECT gen_random_uuid(),%s,%s,%s,%s,%s,1000+t,NOW(),t,
            900+10*sin(t/3.0)+CASE WHEN t>=400 AND t<430 THEN 250 ELSE 0 END
            FROM generate_series(0,899) t""",
            (SESSION, PARTICIPANT, SITE, SPONSOR, DEVICE),
        )
        cur.execute(
            """INSERT INTO eda_samples(id,session_id,participant_id,site_id,sponsor_id,
            device_id,lsl_timestamp,db_insert_time,sample_index,raw_conductance_us,conductance_us)
            SELECT gen_random_uuid(),%s,%s,%s,%s,%s,1000+t,NOW(),t,
            3+0.1*sin(t/4.0)+CASE WHEN t>=400 AND t<430 THEN 2 ELSE 0 END,
            3+0.1*sin(t/4.0)+CASE WHEN t>=400 AND t<430 THEN 2 ELSE 0 END
            FROM generate_series(0,899) t""",
            (SESSION, PARTICIPANT, SITE, SPONSOR, DEVICE),
        )
        cur.execute(
            """INSERT INTO echo_events(session_id,participant_id,site_id,sponsor_id,
            event_type,source,actor_role,zone_label,lsl_timestamp,db_insert_time)
            VALUES(%s,%s,%s,%s,'manual_marker','manual_logging','therapist',
                   'participant_note',1400,NOW())""",
            (SESSION, PARTICIPANT, SITE, SPONSOR),
        )
        cur.execute("UPDATE sessions SET status='closed',closed_at=NOW() WHERE id=%s", (SESSION,))
    return db_conn


@pytest.mark.integration
def test_b001_b009_database_replay_tenancy_and_trigger_audits(batch_session):
    conn = batch_session
    first = run_arc_post_session(conn, SESSION, SPONSOR, site_id=SITE)
    again = run_arc_post_session(conn, SESSION, SPONSOR, site_id=SITE)
    assert first.analysis_id == again.analysis_id
    assert first.artifact == again.artifact
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM analysis_runs WHERE session_id=%s", (SESSION,))
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM session_baselines WHERE session_id=%s", (SESSION,))
        assert cur.fetchone()[0] == first.baseline_row_count
        cur.execute(
            """SELECT event_type,count(*) FROM audit_events WHERE session_id=%s
            AND event_type IN ('arc_batch_complete','arc_interpretation_complete')
            GROUP BY event_type""",
            (SESSION,),
        )
        assert dict(cur.fetchall()) == {"arc_batch_complete": 1, "arc_interpretation_complete": 1}
    with pytest.raises(ARCPostSessionError, match="tenant"):
        run_arc_post_session(conn, SESSION, PARTICIPANT, site_id=SITE)


@pytest.mark.integration
def test_b001_active_session_never_writes_artifacts(batch_session):
    conn = batch_session
    with conn.cursor() as cur:
        cur.execute("UPDATE sessions SET status='active' WHERE id=%s", (SESSION,))
    with pytest.raises(ARCPostSessionError, match="closed"):
        run_arc_post_session(conn, SESSION, SPONSOR, site_id=SITE)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM analysis_runs WHERE session_id=%s", (SESSION,))
        assert cur.fetchone()[0] == 0


def test_b008_injected_convergence_passes_and_noise_event_fails_fdr():
    data, metadata, anchors = _recording()
    anchors.append(
        SimpleNamespace(
            id=2, lsl_timestamp=550.0, event_type="manual_marker", zone_label="participant_note"
        )
    )
    artifact, _, ecps = analyze_recording({}, data, metadata, anchors, _config(), "a" * 64)
    assert [event["passed_fdr"] for event in artifact["events"]] == [True, False]
    assert len(ecps) == 1


def test_b008_sparse_recording_is_explicitly_untestable_not_significant():
    data, metadata, anchors = _recording()
    for modality in ("eda", "hrv"):
        data[modality] = [
            Sample(
                s.timestamp, s.value, flagged=not (s.timestamp < 120 or 400 <= s.timestamp < 430)
            )
            for s in data[modality]
        ]
    artifact, _, ecps = analyze_recording({}, data, metadata, anchors, _config(), "a" * 64)
    event = artifact["events"][0]
    assert event["windows"]["w1"]["eligible"]
    assert not event["testable"]
    assert event["null_excluded_count"] > 500
    assert event["p_value"] == 1
    assert not ecps


def test_b004_short_snippet_and_missing_channel_are_excluded():
    samples = [Sample(i / 100, np.sin(i), channel="one") for i in range(8)]
    result = feature_series("eeg", samples, ["eeg_alpha_power"], origin=0, end=10, epoch_s=10)
    assert result[0].values == (None,)
    samples = [Sample(i / 100, np.sin(i), channel="one") for i in range(1000)]
    result = feature_series(
        "eeg",
        samples,
        ["eeg_alpha_power"],
        origin=0,
        end=10,
        epoch_s=10,
        expected_channels=("one", "two"),
        sample_rate_hz=100,
    )
    assert result[0].values == (None,)


def test_b011_nonfinite_times_are_counted_and_excursions_are_descriptive():
    data, metadata, anchors = _recording()
    data["eda"].append(Sample(float("nan"), 3))
    artifact, _, _ = analyze_recording({}, data, metadata, anchors, _config(), "a" * 64)
    assert artifact["quality_summary"]["eda"]["invalid_timestamp_count"] == 1
    assert artifact["data_excursion_review"]["findings"]
    assert artifact["safety_assessment"].startswith("Not performed")
    canonical_json(artifact)


@pytest.mark.integration
def test_b001_closed_without_watermark_is_rejected(db_conn):
    session_id = "ac000000-0000-4000-8000-000000000006"
    with db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sessions(id,participant_id,site_id,sponsor_id,
            capture_source,compound,status,started_at)
            VALUES(%s,%s,%s,%s,'simulated','psilocybin','closed',NOW())""",
            (session_id, PARTICIPANT, SITE, SPONSOR),
        )
    with pytest.raises(ARCPostSessionError, match="watermark_verified"):
        run_arc_post_session(db_conn, session_id, SPONSOR, site_id=SITE)


@pytest.mark.integration
def test_b001_analysis_refuses_capture_or_backfill_session_lock(db_conn, db_url):
    import psycopg2

    session_id = "ac000000-0000-4000-8000-000000000007"
    other = psycopg2.connect(db_url)
    try:
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (session_id,))
        with pytest.raises(ARCPostSessionError, match="busy"):
            run_arc_post_session(db_conn, session_id, SPONSOR, site_id=SITE)
    finally:
        other.close()
