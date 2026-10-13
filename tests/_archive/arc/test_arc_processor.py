"""Tests for ARC anchor clustering and baseline persistence helpers."""

from pathlib import Path
from uuid import uuid4

import pytest

from batch.arc.processor import (
    DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
    EchoAnchorRow,
    cluster_echo_anchor_rows,
    load_canonical_echo_anchors,
    load_echo_anchor_rows,
    load_session_baselines,
    run_arc_post_session,
)
from config.arc_watchdog import AnchorEventFilter

_PARTICIPANT_ID = "aaaa0000-0000-0000-0000-000000000001"
_SITE_ID = "bbbb0000-0000-0000-0000-000000000001"
_SPONSOR_ID = "cccc0000-0000-0000-0000-000000000001"
_DEVICE_ID = "dddd0000-0000-0000-0000-000000000001"


def _row(row_id: int, lsl_timestamp: float, event_type: str = "zone_enter") -> EchoAnchorRow:
    return EchoAnchorRow(
        id=row_id,
        session_id="11111111-1111-1111-1111-111111111111",
        participant_id=_PARTICIPANT_ID,
        site_id=_SITE_ID,
        sponsor_id=_SPONSOR_ID,
        event_type=event_type,
        source="manual_logging",
        actor_id="therapist_01",
        actor_role="therapist",
        zone_label="arms_reach",
        lsl_timestamp=lsl_timestamp,
    )


def _write_arc_test_config(path: Path) -> None:
    path.write_text(
        """
config_version = "test-001"
config_role = "arc_watchdog"

[baseline]
window_duration_s = 10.0

[baseline.min_sample_count]
eeg = 1
hrv = 1
eda = 1
respiration = 1

[windows.w1]
label = "immediate"
start_s = 0.0
end_s = 30.0

[windows.w2]
label = "near_response"
start_s = 30.0
end_s = 120.0

[windows.w3]
label = "sustained_response"
start_s = 120.0
end_s = 300.0

[fdr]
method = "benjamini_hochberg"
alpha = 0.05
family_scope = "session"

[null_model]
method = "permutation"
permutation_count = 10
random_seed = 20260512

[signal_components]
eeg = ["eeg_alpha_power"]
hrv = ["hrv_rmssd"]
eda = ["eda_mean"]
respiration = ["respiration_rate"]

[signal_availability_profile]
min_modalities_required = 2
require_echo_event = true
missing_signal_policy = "record_available_only"

[[anchor_events.include]]
event_type = "zone_enter"
zone_label = "arms_reach"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _insert_arc_seed_data(cursor, session_id: str) -> None:
    cursor.execute(
        """
        INSERT INTO sessions (
            id, site_id, sponsor_id, participant_id, compound, status
        ) VALUES (
            %s,
            %s::uuid,
            %s::uuid,
            %s::uuid,
            'psilocybin',
            'closed'::session_status
        )
        """,
        (session_id, _SITE_ID, _SPONSOR_ID, _PARTICIPANT_ID),
    )
    cursor.execute(
        """
        INSERT INTO echo_events (
            session_id, participant_id, site_id, sponsor_id, event_type,
            source, actor_id, actor_role, zone_label, lsl_timestamp
        ) VALUES (
            %s, %s::uuid, %s::uuid, %s::uuid,
            'zone_enter', 'manual_logging', 'therapist_01', 'therapist',
            'arms_reach', 100.0
        )
        """,
        (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID),
    )
    cursor.execute(
        """
        INSERT INTO eeg_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            channel_id, voltage, lsl_timestamp, sample_index
        ) VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s::uuid, 'Fz', 12.5, 100.0, 1)
        """,
        (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID, _DEVICE_ID),
    )
    cursor.execute(
        """
        INSERT INTO hrv_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            rr_interval_ms, heart_rate_bpm, lsl_timestamp, sample_index
        ) VALUES
            (%s, %s::uuid, %s::uuid, %s::uuid, %s::uuid, 800.0, 75.0, 101.0, 1),
            (%s, %s::uuid, %s::uuid, %s::uuid, %s::uuid, 790.0, 75.9, 102.0, 2)
        """,
        (
            session_id,
            _PARTICIPANT_ID,
            _SITE_ID,
            _SPONSOR_ID,
            _DEVICE_ID,
            session_id,
            _PARTICIPANT_ID,
            _SITE_ID,
            _SPONSOR_ID,
            _DEVICE_ID,
        ),
    )
    cursor.execute(
        """
        INSERT INTO eda_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            raw_conductance_us, conductance_us, lsl_timestamp, sample_index
        ) VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s::uuid, 4.2, 4.3, 102.0, 1)
        """,
        (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID, _DEVICE_ID),
    )
    cursor.execute(
        """
        INSERT INTO respiration_samples (
            session_id, participant_id, site_id, sponsor_id, device_id,
            raw_amplitude, processed_amplitude, breaths_per_min, lsl_timestamp, sample_index
        ) VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s::uuid, 0.8, 0.9, 14.0, 103.0, 1)
        """,
        (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID, _DEVICE_ID),
    )


class TestEchoAnchorClustering:
    def test_clusters_rows_within_gap_and_preserves_input_order(self):
        rows = [
            _row(3, 100.0),
            _row(1, 100.0),
            _row(2, 107.0),
            _row(4, 119.5),
            _row(5, 128.0),
        ]
        original_ids = [row.id for row in rows]

        clusters = cluster_echo_anchor_rows(rows, debounce_gap_s=10.0)

        assert [row.id for row in rows] == original_ids
        assert [cluster.size for cluster in clusters] == [3, 2]
        assert [cluster.canonical_anchor.id for cluster in clusters] == [1, 4]
        assert clusters[0].start_lsl_timestamp == pytest.approx(100.0)
        assert clusters[0].end_lsl_timestamp == pytest.approx(107.0)
        assert clusters[1].start_lsl_timestamp == pytest.approx(119.5)

    def test_rejects_negative_gap(self):
        with pytest.raises(ValueError, match="non-negative"):
            cluster_echo_anchor_rows([_row(1, 100.0)], debounce_gap_s=-1.0)

    def test_empty_input_returns_empty_tuple(self):
        assert cluster_echo_anchor_rows([]) == ()

    def test_load_canonical_echo_anchors_filters_and_clusters(self, cursor, db_conn):
        session_id = str(uuid4())
        cursor.execute(
            """
            INSERT INTO echo_events (
                session_id, participant_id, site_id, sponsor_id,
                event_type, source, actor_id, actor_role, zone_label, lsl_timestamp
            ) VALUES
                (%s, %s, %s, %s, 'zone_enter', 'manual_logging', 'therapist_01',
                 'therapist', 'arms_reach', 100.0),
                (%s, %s, %s, %s, 'zone_exit', 'manual_logging', 'therapist_01',
                 'therapist', 'arms_reach', 101.0),
                (%s, %s, %s, %s, 'zone_enter', 'manual_logging', 'therapist_01',
                 'therapist', 'arms_reach', 107.0),
                (%s, %s, %s, %s, 'zone_enter', 'manual_logging', 'therapist_01',
                 'therapist', 'arms_reach', 119.0)
            """,
            (
                session_id,
                _PARTICIPANT_ID,
                _SITE_ID,
                _SPONSOR_ID,
                session_id,
                _PARTICIPANT_ID,
                _SITE_ID,
                _SPONSOR_ID,
                session_id,
                _PARTICIPANT_ID,
                _SITE_ID,
                _SPONSOR_ID,
                session_id,
                _PARTICIPANT_ID,
                _SITE_ID,
                _SPONSOR_ID,
            ),
        )
        db_conn.commit()

        anchors = (AnchorEventFilter("zone_enter", "arms_reach"),)
        rows = load_echo_anchor_rows(db_conn, session_id, anchor_filters=anchors)
        canonical = load_canonical_echo_anchors(
            db_conn,
            session_id,
            anchor_filters=anchors,
            debounce_gap_s=DEFAULT_ECHO_CLUSTER_DEBOUNCE_S,
        )

        assert [row.lsl_timestamp for row in rows] == [100.0, 107.0, 119.0]
        assert [row.event_type for row in rows] == ["zone_enter", "zone_enter", "zone_enter"]
        assert [row.lsl_timestamp for row in canonical] == [100.0, 119.0]


@pytest.mark.integration
class TestArcPostSessionPersistence:
    def test_run_arc_post_session_persists_session_baselines(self, db_conn):
        session_id = str(uuid4())
        config_path = Path.cwd() / ".arc_watchdog_test_config.toml"
        _write_arc_test_config(config_path)

        cursor = db_conn.cursor()
        try:
            _insert_arc_seed_data(cursor, session_id)
            result = run_arc_post_session(
                db_conn,
                session_id,
                config_path=str(config_path),
            )

            baselines = load_session_baselines(db_conn, session_id)

            assert result.cluster_count == 1
            assert result.canonical_anchor_count == 1
            assert result.baseline_row_count == 4
            assert len(baselines) == 4
            assert {row.modality for row in baselines} == {
                "eeg",
                "hrv",
                "eda",
                "respiration",
            }
            assert {row.signal_component for row in baselines} == {
                "eeg_alpha_power",
                "hrv_rmssd",
                "eda_mean",
                "respiration_rate",
            }

            rerun = run_arc_post_session(
                db_conn,
                session_id,
                config_path=str(config_path),
            )
            assert rerun.baseline_row_count == 4
            assert len(load_session_baselines(db_conn, session_id)) == 4
        finally:
            cursor.close()
            if config_path.exists():
                config_path.unlink()

    def test_run_arc_post_session_allows_no_output(self, db_conn):
        session_id = str(uuid4())
        config_path = Path.cwd() / ".arc_watchdog_test_config.toml"
        _write_arc_test_config(config_path)

        cursor = db_conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO sessions (
                    id, site_id, sponsor_id, participant_id, compound, status
                ) VALUES (
                    %s,
                    %s::uuid,
                    %s::uuid,
                    %s::uuid,
                    'psilocybin',
                    'closed'::session_status
                )
                """,
                (session_id, _SITE_ID, _SPONSOR_ID, _PARTICIPANT_ID),
            )
            cursor.execute(
                """
                INSERT INTO echo_events (
                    session_id, participant_id, site_id, sponsor_id, event_type,
                    source, actor_id, actor_role, zone_label, lsl_timestamp
                ) VALUES (
                    %s, %s::uuid, %s::uuid, %s::uuid,
                    'zone_enter', 'manual_logging', 'therapist_01', 'therapist',
                    'arms_reach', 100.0
                )
                """,
                (session_id, _PARTICIPANT_ID, _SITE_ID, _SPONSOR_ID),
            )

            result = run_arc_post_session(
                db_conn,
                session_id,
                config_path=str(config_path),
            )

            assert result.cluster_count == 1
            assert result.baseline_row_count == 0
            assert load_session_baselines(db_conn, session_id) == ()
        finally:
            cursor.close()
            if config_path.exists():
                config_path.unlink()
