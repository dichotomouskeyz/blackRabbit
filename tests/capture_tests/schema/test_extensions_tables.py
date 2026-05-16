"""Tests for DB extensions, tables, and hypertables."""

import pytest

from tests.capture_tests.schema.support import is_hypertable, table_exists


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
        "participant_consent_log",
        "schema_version_log",
        "electronic_signatures",
        "investigational_product_log",
        "adverse_event_log",
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
