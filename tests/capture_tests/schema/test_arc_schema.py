"""Tests for ARC-specific schema: session_baselines and event_composite_profiles."""

from uuid import uuid4

import psycopg2
import pytest

from tests.capture_tests.schema.support import column_exists


class TestARCSchema:
    SESSION_BASELINE_COLUMNS = [
        "session_id",
        "participant_id",
        "site_id",
        "sponsor_id",
        "modality",
        "signal_component",
        "baseline_mean",
        "baseline_std",
        "baseline_window_start",
        "baseline_window_end",
        "sample_count",
        "created_at",
    ]

    EVENT_COMPOSITE_PROFILE_COLUMNS = [
        "id",
        "session_id",
        "participant_id",
        "site_id",
        "sponsor_id",
        "echo_event_id",
        "w1_convergence_density",
        "w2_convergence_density",
        "w3_convergence_density",
        "w1_participating_signals",
        "w2_participating_signals",
        "w3_participating_signals",
        "deviation_metrics",
        "null_threshold",
        "fdr_q_value",
        "passed_fdr",
        "temporal_alignment_score",
        "sap_available_signals",
        "sap_participating_signals",
        "arc_config_version",
        "arc_config_sha256",
        "created_at",
    ]

    @pytest.mark.parametrize("column_name", SESSION_BASELINE_COLUMNS)
    def test_session_baselines_columns_exist(self, cursor, column_name):
        assert column_exists(cursor, "session_baselines", column_name), (
            f"session_baselines missing {column_name}"
        )

    @pytest.mark.parametrize("column_name", EVENT_COMPOSITE_PROFILE_COLUMNS)
    def test_event_composite_profiles_columns_exist(self, cursor, column_name):
        assert column_exists(cursor, "event_composite_profiles", column_name), (
            f"event_composite_profiles missing {column_name}"
        )

    def test_deviation_metrics_is_jsonb(self, cursor):
        cursor.execute(
            """
            SELECT data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'event_composite_profiles'
              AND column_name = 'deviation_metrics';
            """
        )
        data_type, udt_name = cursor.fetchone()
        assert data_type == "jsonb"
        assert udt_name == "jsonb"

    def test_event_composite_profiles_rejects_failed_fdr(self, cursor):
        cursor.execute(
            """
            INSERT INTO echo_events
                (session_id, participant_id, site_id, sponsor_id, event_type,
                 source, actor_id, actor_role, zone_label, lsl_timestamp)
            VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a17',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'zone_enter', 'manual_logging', 'C01', 'coordinator', 'in_room', 1234567890.0)
            RETURNING id;
            """
        )
        echo_event_id = cursor.fetchone()[0]

        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute(
                """
                INSERT INTO event_composite_profiles (
                    session_id, participant_id, site_id, sponsor_id, echo_event_id,
                    w1_convergence_density, w2_convergence_density, w3_convergence_density,
                    deviation_metrics, null_threshold, fdr_q_value, passed_fdr,
                    temporal_alignment_score, arc_config_version, arc_config_sha256
                )
                VALUES (
                    'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a17',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    %s,
                    0.33, 0.50, 0.66,
                    '{"w1": {"hrv_rmssd": {"z_score": 0.5, "p_value": 0.50}}}'::jsonb,
                    0.95, 0.50, FALSE, 0.12,
                    'arc_watchdog_config.toml@demo-001',
                    '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
                );
                """,
                (echo_event_id,),
            )

    def test_event_composite_profile_insert_triggers_audit(self, cursor):
        session_id = str(uuid4())
        cursor.execute(
            """
            INSERT INTO session_baselines (
                session_id, participant_id, site_id, sponsor_id, modality,
                signal_component, baseline_mean, baseline_std,
                baseline_window_start, baseline_window_end, sample_count
            )
            VALUES (
                %s,
                'aaaa0000-0000-0000-0000-000000000001',
                'bbbb0000-0000-0000-0000-000000000001',
                'cccc0000-0000-0000-0000-000000000001',
                'hrv', 'hrv_rmssd', 42.0, 3.5, 1000.0, 1120.0, 120
            );
            """,
            (session_id,),
        )
        cursor.execute(
            """
            INSERT INTO echo_events
                (session_id, participant_id, site_id, sponsor_id, event_type,
                 source, actor_id, actor_role, zone_label, lsl_timestamp)
            VALUES (%s,
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'zone_enter', 'manual_logging', 'C01', 'coordinator', 'in_room', 1234567890.0)
            RETURNING id;
            """,
            (session_id,),
        )
        echo_event_id = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO event_composite_profiles (
                session_id, participant_id, site_id, sponsor_id, echo_event_id,
                w1_convergence_density, w2_convergence_density, w3_convergence_density,
                w1_participating_signals, w2_participating_signals, w3_participating_signals,
                deviation_metrics, null_threshold, fdr_q_value, passed_fdr,
                temporal_alignment_score, sap_available_signals, sap_participating_signals,
                arc_config_version, arc_config_sha256
            )
            VALUES (
                %s,
                'aaaa0000-0000-0000-0000-000000000001',
                'bbbb0000-0000-0000-0000-000000000001',
                'cccc0000-0000-0000-0000-000000000001',
                %s,
                0.33, 0.50, 0.66,
                '["hrv_rmssd"]'::jsonb,
                '["hrv_rmssd", "eda_mean"]'::jsonb,
                '["hrv_rmssd", "eda_mean", "eeg_alpha_power"]'::jsonb,
                '{"w1": {"hrv_rmssd": {"z_score": 2.4, "p_value": 0.002}}}'::jsonb,
                0.95, 0.004, TRUE, 0.88,
                '["hrv_rmssd", "eda_mean", "eeg_alpha_power"]'::jsonb,
                '["hrv_rmssd", "eda_mean"]'::jsonb,
                'arc_watchdog_config.toml@demo-001',
                '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
            );
            """,
            (session_id, echo_event_id),
        )
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE session_id = %s
              AND table_name = 'event_composite_profiles';
            """,
            (session_id,),
        )
        assert cursor.fetchone()[0] >= 1, (
            "Audit trigger did not fire on event_composite_profiles INSERT"
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM session_baselines
            WHERE session_id = %s AND modality = 'hrv' AND signal_component = 'hrv_rmssd';
            """,
            (session_id,),
        )
        assert cursor.fetchone()[0] == 1
