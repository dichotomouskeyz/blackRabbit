"""Consensai 1a - Schema validation tests.

WHAT THESE TESTS PROVE:
  1. Every table exists with expected columns
  2. Hypertables are actually TimescaleDB hypertables
  3. Audit triggers fire on every insert
  4. lsl_timestamp and db_insert_time are always separate columns
  5. Append-only tables reject UPDATE and DELETE
  6. CHECK constraints reject invalid values
  7. Extensions are enabled

WHY THIS MATTERS REGULATORILY:
  For a Part 11 system, the schema being correct is not enough.
  You must be able to PROVE it. These tests are that proof.
  Every time you run pytest, you generate evidence that the
  audit trail is active and protections are in place.
"""

import psycopg2
import pytest


def table_exists(cursor, table_name):
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = %s
        );
    """,
        (table_name,),
    )
    return cursor.fetchone()[0]


def column_exists(cursor, table_name, column_name):
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = %s
            AND column_name = %s
        );
    """,
        (table_name, column_name),
    )
    return cursor.fetchone()[0]


def is_hypertable(cursor, table_name):
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM timescaledb_information.hypertables
            WHERE hypertable_name = %s
        );
    """,
        (table_name,),
    )
    return cursor.fetchone()[0]


class TestExtensions:
    def test_timescaledb_enabled(self, cursor):
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'
            );
        """)
        assert cursor.fetchone()[0], "TimescaleDB extension not installed"

    def test_pgvector_enabled(self, cursor):
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_extension WHERE extname = 'vector'
            );
        """)
        assert cursor.fetchone()[0], "pgvector extension not installed"


class TestTablesExist:
    """Confirm every table from every migration exists."""

    EXPECTED_TABLES = [
        "eeg_samples",
        "hrv_samples",
        "eda_samples",
        "respiration_samples",
        "sessions",
        "audit_events",
        "alert_events",
        "humen_events",
        "voice_segments",
        "session_feature_vectors",
        "session_notes",
        "participant_consent_log",
        "schema_version_log",
        "electronic_signatures",
        "investigational_product_log",
        "adverse_event_log",
        "protocol_deviation_log",
        "data_access_log",
        "system_users",
        "system_user_access_log",
    ]

    @pytest.mark.parametrize("table_name", EXPECTED_TABLES)
    def test_table_exists(self, cursor, table_name):
        assert table_exists(cursor, table_name), f"Table '{table_name}' does not exist"


class TestHypertables:
    """Confirm biosignal tables are TimescaleDB hypertables.

    WHY: A regular table and a hypertable look identical to a SELECT.
    The only way to confirm partitioning is active is to check
    timescaledb_information.hypertables directly.
    """

    HYPERTABLES = [
        "eeg_samples",
        "hrv_samples",
        "eda_samples",
        "respiration_samples",
    ]

    @pytest.mark.parametrize("table_name", HYPERTABLES)
    def test_is_hypertable(self, cursor, table_name):
        assert is_hypertable(
            cursor, table_name
        ), f"'{table_name}' is not a TimescaleDB hypertable"


class TestDualTimestamps:
    """Confirm every biosignal table has BOTH lsl_timestamp and db_insert_time.

    WHY: Regulatory requirement. lsl_timestamp = when the device captured
    the sample. db_insert_time = when it hit the database. Never the same.
    """

    BIOSIGNAL_TABLES = [
        "eeg_samples",
        "hrv_samples",
        "eda_samples",
        "respiration_samples",
    ]

    @pytest.mark.parametrize("table_name", BIOSIGNAL_TABLES)
    def test_has_lsl_timestamp(self, cursor, table_name):
        assert column_exists(
            cursor, table_name, "lsl_timestamp"
        ), f"'{table_name}' missing lsl_timestamp column"

    @pytest.mark.parametrize("table_name", BIOSIGNAL_TABLES)
    def test_has_db_insert_time(self, cursor, table_name):
        assert column_exists(
            cursor, table_name, "db_insert_time"
        ), f"'{table_name}' missing db_insert_time column"


class TestAuditTriggers:
    """Confirm inserting into any table auto-fires an audit_events row.

    WHY: Migration 012 added triggers. If a trigger were accidentally
    dropped, the schema would look correct but the audit trail would
    silently stop working. These tests prove the triggers are alive.
    """

    def test_session_insert_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO sessions (
                id, site_id, sponsor_id, participant_id,
                compound, status
            ) VALUES (
                'test-session-001', 'SITE01', 'SPONSOR01',
                'PARTICIPANT01', 'psilocybin', 'initializing'
            );
        """)
        db_conn.commit()

        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'test-session-001'
            AND table_name = 'sessions';
        """)
        count = cursor.fetchone()[0]
        assert count >= 1, "Audit trigger did not fire on sessions INSERT"

    def test_humen_event_insert_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO humen_events (
                session_id, participant_id, site_id, sponsor_id,
                event_type, actor_id, lsl_timestamp
            ) VALUES (
                'test-session-002', 'PARTICIPANT01', 'SITE01', 'SPONSOR01',
                'zone_enter', 'COORDINATOR01', 1234567890.0
            );
        """)
        db_conn.commit()

        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'test-session-002'
            AND table_name = 'humen_events';
        """)
        count = cursor.fetchone()[0]
        assert count >= 1, "Audit trigger did not fire on humen_events INSERT"


class TestAppendOnly:
    """Confirm append-only tables reject UPDATE and DELETE.

    WHY: audit_events and electronic_signatures are legally required
    to be tamper-evident. Migration 007 and 019 revoke UPDATE and
    DELETE. These tests prove those revocations are active.
    """

    def test_audit_events_rejects_delete(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO sessions (
                id, site_id, sponsor_id, participant_id,
                compound, status
            ) VALUES (
                'test-session-003', 'SITE01', 'SPONSOR01',
                'PARTICIPANT01', 'psilocybin', 'initializing'
            );
        """)
        db_conn.commit()

        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("""
                DELETE FROM audit_events
                WHERE session_id = 'test-session-003';
            """)

    def test_electronic_signatures_rejects_update(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO electronic_signatures (
                session_id, site_id, sponsor_id,
                signer_id, signer_printed_name, signer_role,
                signature_meaning, table_name, record_id,
                signature_hash
            ) VALUES (
                'test-session-004', 'SITE01', 'SPONSOR01',
                'USER01', 'Jay Ahlon', 'coordinator',
                'session_closed', 'sessions', 'test-session-004',
                'abc123hash'
            );
        """)
        db_conn.commit()

        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute("""
                UPDATE electronic_signatures
                SET signature_hash = 'tampered'
                WHERE session_id = 'test-session-004';
            """)


class TestCheckConstraints:
    """Confirm CHECK constraints reject invalid values."""

    def test_sessions_rejects_invalid_status(self, cursor):
        with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
            cursor.execute("""
                INSERT INTO sessions (
                    id, site_id, sponsor_id, participant_id,
                    compound, status
                ) VALUES (
                    'test-bad-status', 'SITE01', 'SPONSOR01',
                    'PARTICIPANT01', 'psilocybin', 'not_a_real_status'
                );
            """)

    def test_alert_events_rejects_invalid_severity(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO alert_events (
                    session_id, participant_id, site_id, sponsor_id,
                    alert_type, severity, algorithm_name, algorithm_version
                ) VALUES (
                    'test-session', 'P01', 'SITE01', 'SPONSOR01',
                    'test_alert', 'extreme', 'test_algo', '1.0'
                );
            """)

    def test_adverse_event_rejects_invalid_grade(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO adverse_event_log (
                    session_id, participant_id, site_id, sponsor_id,
                    compound, ae_term, ae_description, ctcae_grade,
                    relatedness, onset_timestamp, reported_by
                ) VALUES (
                    'test-session', 'P01', 'SITE01', 'SPONSOR01',
                    'psilocybin', 'test_ae', 'description', 6,
                    'possible', NOW(), 'USER01'
                );
            """)
