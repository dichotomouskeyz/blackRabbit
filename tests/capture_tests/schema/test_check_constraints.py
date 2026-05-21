"""Tests for CHECK constraints on enum-backed columns."""

import psycopg2
import pytest


class TestCheckConstraints:
    def test_sessions_rejects_invalid_status(self, cursor):
        with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
            cursor.execute("""
                INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
                VALUES (
                    'a0eebc99-0000-0000-ffff-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'psilocybin', 'not_valid'
                );
            """)

    def test_alert_events_rejects_invalid_severity(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO alert_events
                    (session_id, participant_id, site_id, sponsor_id, alert_type,
                     compound, compound_dose, severity, algorithm_name, algorithm_version)
                VALUES (
                    'a0eebc99-0000-0000-0000-000000000099',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'cardiac', 'psilocybin', 0.0, 'extreme', 'algo', '1.0'
                );
            """)

    def test_sessions_rejects_removed_paused_status(self, cursor):
        with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
            cursor.execute("""
                INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
                VALUES (
                    'a0eebc99-0000-0000-ffff-000000000002',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'psilocybin', 'paused'
                );
            """)

    def test_echo_events_rejects_invalid_event_type(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO echo_events
                    (session_id, participant_id, site_id, sponsor_id, event_type,
                     source, actor_id, actor_role, zone_label, lsl_timestamp)
                VALUES (
                    'a0eebc99-0000-0000-0000-000000000099',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'invalid_event', 'manual_logging', 'C01', 'coordinator',
                    'in_room', 1.0
                );
            """)

    def test_echo_events_rejects_proximity_state_change_event_type(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO echo_events
                    (session_id, participant_id, site_id, sponsor_id, event_type,
                     source, actor_id, actor_role, zone_label, lsl_timestamp)
                VALUES (
                    'a0eebc99-0000-0000-0000-000000000097',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'proximity_state_change', 'manual_logging', 'C01', 'coordinator',
                    'in_room', 1.0
                );
            """)

    def test_echo_events_rejects_null_actor_role(self, cursor):
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cursor.execute("""
                INSERT INTO echo_events
                    (session_id, participant_id, site_id, sponsor_id, event_type,
                     source, actor_id, zone_label, lsl_timestamp)
                VALUES (
                    'a0eebc99-0000-0000-0000-000000000098',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'zone_enter', 'manual_logging', 'C01', 'in_room', 1.0
                );
            """)
