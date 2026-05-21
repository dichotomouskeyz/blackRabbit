"""Tests for DB extensions, tables, and hypertables."""

import pytest

from tests.capture_tests.schema.support import column_exists, is_hypertable, table_exists


class TestExtensions:
    def test_timescaledb_enabled(self, cursor):
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb');")
        assert cursor.fetchone()[0], "TimescaleDB extension not installed"

    def test_pgvector_enabled(self, cursor):
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector');")
        assert cursor.fetchone()[0], "pgvector extension not installed"


class TestTablesExist:
    EXPECTED_TABLES = [
        "eeg_samples",
        "hrv_samples",
        "eda_samples",
        "respiration_samples",
        "sessions",
        "compound_reference",
        "audit_events",
        "alert_events",
        "echo_events",
        "schema_version_log",
        "session_signal_metadata",
        "data_correction_amendment_log",
        "session_environment_log",
        "session_baselines",
        "event_composite_profiles",
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


class TestBiosignalIntegrityLog:
    def test_log_type_column_exists(self, cursor):
        assert column_exists(cursor, "biosignal_integrity_log", "log_type")

    def test_hash_method_column_exists(self, cursor):
        assert column_exists(cursor, "biosignal_integrity_log", "hash_method")

    def test_reconciliation_report_column_exists(self, cursor):
        assert column_exists(cursor, "biosignal_integrity_log", "reconciliation_report")


class TestSessionSignalMetadata:
    def test_eeg_channel_names_column_exists(self, cursor):
        assert column_exists(cursor, "session_signal_metadata", "eeg_channel_names")
