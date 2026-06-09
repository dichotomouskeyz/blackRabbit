"""Tests for dual-timestamp column existence on biosignal tables."""

import pytest

from tests.capture_tests.schema.support import column_exists


class TestDualTimestamps:
    BIOSIGNAL_TABLES = [
        "eeg_samples",
        "hrv_samples",
        "eda_samples",
        "respiration_samples",
    ]

    @pytest.mark.parametrize("table_name", BIOSIGNAL_TABLES)
    def test_has_lsl_timestamp(self, cursor, table_name):
        assert column_exists(cursor, table_name, "lsl_timestamp"), (
            f"'{table_name}' missing lsl_timestamp"
        )

    @pytest.mark.parametrize("table_name", BIOSIGNAL_TABLES)
    def test_has_db_insert_time(self, cursor, table_name):
        assert column_exists(cursor, table_name, "db_insert_time"), (
            f"'{table_name}' missing db_insert_time"
        )
