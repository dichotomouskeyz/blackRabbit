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
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb');"
        )
        assert cursor.fetchone()[0], "TimescaleDB extension not installed"

    def test_pgvector_enabled(self, cursor):
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector');"
        )
        assert cursor.fetchone()[0], "pgvector extension not installed"


class TestTablesExist:
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
    HYPERTABLES = ["eeg_samples", "hrv_samples", "eda_samples", "respiration_samples"]

    @pytest.mark.parametrize("table_name", HYPERTABLES)
    def test_is_hypertable(self, cursor, table_name):
        assert is_hypertable(cursor, table_name), f"'{table_name}' is not a hypertable"


class TestDualTimestamps:
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
        ), f"'{table_name}' missing lsl_timestamp"

    @pytest.mark.parametrize("table_name", BIOSIGNAL_TABLES)
    def test_has_db_insert_time(self, cursor, table_name):
        assert column_exists(
            cursor, table_name, "db_insert_time"
        ), f"'{table_name}' missing db_insert_time"


class TestAuditTriggers:
    def test_session_insert_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES ('test-session-001', 'SITE01', 'SPONSOR01', 'P01', 'psilocybin', 'initializing');
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'test-session-001' AND table_name = 'sessions';
        """)
        assert (
            cursor.fetchone()[0] >= 1
        ), "Audit trigger did not fire on sessions INSERT"

    def test_humen_event_insert_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO humen_events
                (session_id, participant_id, site_id, sponsor_id, event_type, actor_id, lsl_timestamp)
            VALUES ('test-session-002', 'P01', 'SITE01', 'SPONSOR01', 'zone_enter', 'C01', 1234567890.0);
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'test-session-002' AND table_name = 'humen_events';
        """)
        assert (
            cursor.fetchone()[0] >= 1
        ), "Audit trigger did not fire on humen_events INSERT"


class TestAppendOnly:
    def test_audit_events_rejects_delete(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
            VALUES ('test-session-003', 'SITE01', 'SPONSOR01', 'P01', 'psilocybin', 'initializing');
        """)
        db_conn.commit()
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute(
                "DELETE FROM audit_events WHERE session_id = 'test-session-003';"
            )

    def test_electronic_signatures_rejects_update(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO electronic_signatures
                (session_id, site_id, sponsor_id, signer_id, signer_printed_name,
                 signer_role, signature_meaning, table_name, record_id, signature_hash)
            VALUES ('test-session-004', 'SITE01', 'SPONSOR01', 'USER01', 'Jay Ahlon',
                    'coordinator', 'session_closed', 'sessions', 'test-session-004', 'abc123');
        """)
        db_conn.commit()
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE electronic_signatures SET signature_hash = 'tampered' WHERE session_id = 'test-session-004';"
            )


class TestCheckConstraints:
    def test_sessions_rejects_invalid_status(self, cursor):
        with pytest.raises(psycopg2.errors.InvalidTextRepresentation):
            cursor.execute("""
                INSERT INTO sessions (id, site_id, sponsor_id, participant_id, compound, status)
                VALUES ('bad-status', 'SITE01', 'SPONSOR01', 'P01', 'psilocybin', 'not_valid');
            """)

    def test_alert_events_rejects_invalid_severity(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO alert_events
                    (session_id, participant_id, site_id, sponsor_id, alert_type,
                     severity, algorithm_name, algorithm_version)
                VALUES ('s', 'p', 'SITE01', 'SPONSOR01', 'test', 'extreme', 'algo', '1.0');
            """)

    def test_adverse_event_rejects_invalid_grade(self, cursor):
        with pytest.raises(psycopg2.errors.CheckViolation):
            cursor.execute("""
                INSERT INTO adverse_event_log
                    (session_id, participant_id, site_id, sponsor_id, compound,
                     ae_term, ae_description, ctcae_grade, relatedness, onset_timestamp, reported_by)
                VALUES ('s', 'p', 'SITE01', 'SPONSOR01', 'psilocybin',
                        'ae', 'desc', 6, 'possible', NOW(), 'USER01');
            """)
