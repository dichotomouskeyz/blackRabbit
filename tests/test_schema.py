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
        # Biosignal hypertables
        "eeg_samples",
        "hrv_samples",
        "eda_samples",
        "respiration_samples",
        # Core clinical tables
        "sessions",
        "compound_reference",
        "audit_events",
        "alert_events",
        "humen_events",
        # Regulatory tables
        "participant_consent_log",
        "schema_version_log",
        "electronic_signatures",
        "investigational_product_log",
        "adverse_event_log",
        # Recording and compliance tables
        "session_signal_metadata",
        "data_correction_amendment_log",
        "session_environment_log",
        # Feature and notes tables
        "session_feature_vectors",
        "session_notes",
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
            VALUES (
                'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11',
                'a0eebc99-0000-0000-0000-000000000001',
                'a0eebc99-0000-0000-0000-000000000002',
                'a0eebc99-0000-0000-0000-000000000003',
                'psilocybin', 'initializing'
            ) ON CONFLICT (id) DO NOTHING;
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11' AND table_name = 'sessions';
        """)
        assert (
            cursor.fetchone()[0] >= 1
        ), "Audit trigger did not fire on sessions INSERT"

    def test_humen_event_insert_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO humen_events
                (session_id, participant_id, site_id, sponsor_id, event_type,
                 source, actor_id, zone_label, lsl_timestamp)
            VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'zone_enter', 'manual_logging', 'C01', 'in_room', 1234567890.0);
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12' AND table_name = 'humen_events';
        """)
        assert (
            cursor.fetchone()[0] >= 1
        ), "Audit trigger did not fire on humen_events INSERT"

    def test_watchdog_process_restart_triggers_audit(self, cursor, db_conn):
        cursor.execute("""
            INSERT INTO alert_events (
                session_id, participant_id, site_id, sponsor_id,
                alert_type, compound, compound_dose, severity,
                algorithm_name, algorithm_version, algorithm_parameters,
                message
            ) VALUES (
                'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a14',
                'aaaa0000-0000-0000-0000-000000000001',
                'bbbb0000-0000-0000-0000-000000000001',
                'cccc0000-0000-0000-0000-000000000001',
                'process_restart', 'psilocybin', 25.0, 'warning',
                'watchdog', '1.0.0',
                '{"exit_code": 1, "restart_count": 1, "uptime_s": 42.0}'::jsonb,
                'lsl_forwarder exited with code 1, restarting (attempt 1/5)'
            );
        """)
        db_conn.commit()
        cursor.execute("""
            SELECT COUNT(*) FROM audit_events
            WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a14'
              AND table_name = 'alert_events';
        """)
        assert (
            cursor.fetchone()[0] >= 1
        ), "Audit trigger did not fire on watchdog process_restart INSERT"


class TestAppendOnly:
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
                "DELETE FROM audit_events WHERE session_id = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13';"
            )

    def test_electronic_signatures_rejects_update(
        self, restricted_cursor, restricted_conn
    ):
        restricted_cursor.execute("""
            INSERT INTO electronic_signatures
                (session_id, site_id, sponsor_id, signer_id, signer_printed_name,
                 signer_role, signature_meaning, table_name, record_id, signature_hash)
            VALUES ('a0eebc99-0000-0000-0000-000000000004',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'USER01', 'Jay Ahlon',
                    'coordinator', 'session_closed', 'sessions', 'rec-004', 'abc123');
        """)
        restricted_conn.commit()
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            restricted_cursor.execute(
                "UPDATE electronic_signatures SET signature_hash = 'tampered' "
                "WHERE session_id = 'a0eebc99-0000-0000-0000-000000000004';"
            )


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
                     ae_term, ae_description, ctcae_grade, relatedness, onset_timestamp, reported_by)
                VALUES (
                    'a0eebc99-0000-0000-0000-000000000099',
                    'aaaa0000-0000-0000-0000-000000000001',
                    'bbbb0000-0000-0000-0000-000000000001',
                    'cccc0000-0000-0000-0000-000000000001',
                    'psilocybin', 'ae', 'desc', 6, 'possible', NOW(), 'USER01'
                );
            """)


# ---------------------------------------------------------------------------
# Fixtures shared by TestTimestampSeparation and TestMetadataIntegrity
# ---------------------------------------------------------------------------

_TS_SESSION = "ffff0000-0000-0000-0000-000000000001"
_TS_PARTICIPANT = "ffff0001-0000-0000-0000-000000000001"
_TS_SITE = "ffff0002-0000-0000-0000-000000000001"
_TS_SPONSOR = "ffff0003-0000-0000-0000-000000000001"
_TS_DEVICE = "ffff0004-0000-0000-0000-000000000001"
_TS_LSL = 12345.678901  # LSL clock space — never equals Unix epoch (~1.7 B)


@pytest.fixture
def biosignal_rows(cursor, db_conn):
    """Insert one sample into each hypertable and commit."""
    cursor.execute(
        """
        INSERT INTO eeg_samples
            (session_id, participant_id, site_id, sponsor_id, device_id,
             channel_id, voltage, lsl_timestamp, sample_index)
        VALUES (%s, %s, %s, %s, %s, 'ch_0', 42.5, %s, 0)
        """,
        (_TS_SESSION, _TS_PARTICIPANT, _TS_SITE, _TS_SPONSOR, _TS_DEVICE, _TS_LSL),
    )
    cursor.execute(
        """
        INSERT INTO hrv_samples
            (session_id, participant_id, site_id, sponsor_id, device_id,
             rr_interval_ms, lsl_timestamp, sample_index)
        VALUES (%s, %s, %s, %s, %s, 850.0, %s, 0)
        """,
        (_TS_SESSION, _TS_PARTICIPANT, _TS_SITE, _TS_SPONSOR, _TS_DEVICE, _TS_LSL),
    )
    cursor.execute(
        """
        INSERT INTO eda_samples
            (session_id, participant_id, site_id, sponsor_id, device_id,
             raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
        VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, 0)
        """,
        (_TS_SESSION, _TS_PARTICIPANT, _TS_SITE, _TS_SPONSOR, _TS_DEVICE, _TS_LSL),
    )
    cursor.execute(
        """
        INSERT INTO respiration_samples
            (session_id, participant_id, site_id, sponsor_id, device_id,
             raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
        VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, 0)
        """,
        (_TS_SESSION, _TS_PARTICIPANT, _TS_SITE, _TS_SPONSOR, _TS_DEVICE, _TS_LSL),
    )
    db_conn.commit()
    yield


_BIOSIGNAL_TABLES = ["eeg_samples", "hrv_samples", "eda_samples", "respiration_samples"]


class TestTimestampSeparation:
    """lsl_timestamp and db_insert_time must always be distinct on every biosignal row.

    lsl_timestamp: device capture time in LSL clock space (seconds since system
                   boot, typically a small number like 12345).
    db_insert_time: PostgreSQL wall clock at write time (Unix epoch, ~1.7 billion).

    They measure different things with different epochs and can never be
    numerically equal. Any collapse would erase the capture-vs-storage
    distinction required by 21 CFR Part 11.
    """

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_timestamps_never_equal(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s"
            " AND EXTRACT(EPOCH FROM db_insert_time) = lsl_timestamp",
            (_TS_SESSION,),
        )
        assert (
            cursor.fetchone()[0] == 0
        ), f"{table}: lsl_timestamp equals db_insert_time on some rows"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_lsl_timestamp_not_null(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s AND lsl_timestamp IS NULL",
            (_TS_SESSION,),
        )
        assert cursor.fetchone()[0] == 0, f"{table}: NULL lsl_timestamp found"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_db_insert_time_not_null(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s AND db_insert_time IS NULL",
            (_TS_SESSION,),
        )
        assert cursor.fetchone()[0] == 0, f"{table}: NULL db_insert_time found"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_db_insert_time_is_recent(self, cursor, biosignal_rows, table):
        """db_insert_time must be a real wall-clock time, not a stale or epoch value."""
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s"
            " AND db_insert_time < NOW() - INTERVAL '1 year'",
            (_TS_SESSION,),
        )
        assert (
            cursor.fetchone()[0] == 0
        ), f"{table}: db_insert_time is more than 1 year old — possible timestamp collapse"


class TestMetadataIntegrity:
    """Every biosignal row must carry correct, non-null session metadata.

    Verifies that the forwarder injected session_id, participant_id, site_id,
    sponsor_id, device_id, lsl_timestamp, and sample_index on every row.
    A NULL or wrong value in any of these fields breaks tenancy isolation,
    audit traceability, and regulatory traceability requirements.
    """

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_rows_exist(self, cursor, biosignal_rows, table):
        """Sanity check: confirms the fixture successfully wrote rows."""
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s",
            (_TS_SESSION,),
        )
        assert (
            cursor.fetchone()[0] > 0
        ), f"{table}: no test rows found — fixture INSERT may have failed"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_no_null_required_fields(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE session_id = %s
              AND (session_id IS NULL OR participant_id IS NULL
                OR site_id    IS NULL OR sponsor_id    IS NULL
                OR device_id  IS NULL OR lsl_timestamp IS NULL
                OR sample_index IS NULL)
            """,
            (_TS_SESSION,),
        )
        assert (
            cursor.fetchone()[0] == 0
        ), f"{table}: NULL found in a required metadata field"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_participant_id_correct(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s AND participant_id != %s",
            (_TS_SESSION, _TS_PARTICIPANT),
        )
        assert cursor.fetchone()[0] == 0, f"{table}: wrong participant_id on some rows"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_site_id_correct(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s AND site_id != %s",
            (_TS_SESSION, _TS_SITE),
        )
        assert cursor.fetchone()[0] == 0, f"{table}: wrong site_id on some rows"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_sponsor_id_correct(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s AND sponsor_id != %s",
            (_TS_SESSION, _TS_SPONSOR),
        )
        assert cursor.fetchone()[0] == 0, f"{table}: wrong sponsor_id on some rows"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_device_id_correct(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s AND device_id != %s",
            (_TS_SESSION, _TS_DEVICE),
        )
        assert cursor.fetchone()[0] == 0, f"{table}: wrong device_id on some rows"

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_lsl_timestamp_value_correct(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s AND lsl_timestamp != %s",
            (_TS_SESSION, _TS_LSL),
        )
        assert (
            cursor.fetchone()[0] == 0
        ), f"{table}: wrong lsl_timestamp value on some rows"
