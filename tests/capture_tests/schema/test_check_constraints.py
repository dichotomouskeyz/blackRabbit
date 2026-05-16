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

    def test_adverse_event_rejects_invalid_grade(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO adverse_event_log
                    (session_id, participant_id, site_id, sponsor_id, compound,
                     ae_term, ae_description, ctcae_grade, relatedness,
                     onset_timestamp, reported_by)
                VALUES (
                    'a0eebc99-0000-0000-0000-000000000099',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'psilocybin', 'ae', 'desc', 6, 'possible', NOW(), 'USER01'
                );
            """)
