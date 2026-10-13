"""Tests for append-only enforcement on sensitive schema tables."""

import psycopg2
import pytest


class TestAppendOnly:
    def test_event_composite_profiles_rejects_update(self, cursor, db_conn, restricted_cursor):
        session_id = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a16"
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
                deviation_metrics, null_threshold, fdr_q_value, passed_fdr,
                temporal_alignment_score, arc_config_version, arc_config_sha256
            )
            VALUES (
                %s,
                'aaaa0000-0000-0000-0000-000000000001',
                'bbbb0000-0000-0000-0000-000000000001',
                'cccc0000-0000-0000-0000-000000000001',
                %s,
                0.33, 0.50, 0.66,
                '{"w1": {"hrv_rmssd": {"z_score": 2.4, "p_value": 0.002}}}'::jsonb,
                0.95, 0.004, TRUE, 0.88,
                'arc_watchdog_config.toml@demo-001',
                '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
            );
            """,
            (session_id, echo_event_id),
        )
        db_conn.commit()

        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            restricted_cursor.execute(
                """
                UPDATE event_composite_profiles
                SET passed_fdr = FALSE
                WHERE session_id = %s;
                """,
                (session_id,),
            )

    def test_audit_events_rejects_delete(self, cursor, db_conn, restricted_cursor):
        cursor.execute("""
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES (
                'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13',
                'a0eebc99-0000-0000-0000-000000000001',
                'a0eebc99-0000-0000-0000-000000000002',
                'a0eebc99-0000-0000-0000-000000000003',
                'psilocybin', 'initializing'
            ) ON CONFLICT (id) DO NOTHING;
        """)
        db_conn.commit()
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            restricted_cursor.execute(
                "DELETE FROM audit_events"
                " WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13';"
            )
