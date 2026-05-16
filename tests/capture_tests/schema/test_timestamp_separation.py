"""Tests verifying lsl_timestamp and db_insert_time are always distinct."""

import pytest

from tests.capture_tests.schema.support import (
    _BIOSIGNAL_TABLES,
    _TS_LSL,
    _TS_SESSION,
)


class TestTimestampSeparation:
    """lsl_timestamp and db_insert_time must always be distinct on every biosignal row.

    lsl_timestamp: device capture time in LSL clock space (seconds since system
                   boot, typically a small number like 12345).
    db_insert_time: PostgreSQL wall clock at write time (Unix epoch, ~1.7 billion).

    They measure different things with different epochs and can never be
    numerically equal.
    """

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_timestamps_never_equal(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s"
            " AND EXTRACT(EPOCH FROM db_insert_time) = lsl_timestamp",
            (_TS_SESSION,),
        )
        assert cursor.fetchone()[0] == 0, (
            f"{table}: lsl_timestamp equals db_insert_time on some rows"
        )

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
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s"
            " AND db_insert_time < NOW() - INTERVAL '1 year'",
            (_TS_SESSION,),
        )
        assert cursor.fetchone()[0] == 0, (
            f"{table}: db_insert_time is more than 1 year old — possible timestamp collapse"
        )
