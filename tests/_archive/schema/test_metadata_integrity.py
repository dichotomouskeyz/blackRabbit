"""Tests verifying every biosignal row carries correct, non-null session metadata."""

import pytest

from tests.capture_tests.schema.support import (
    _BIOSIGNAL_TABLES,
    _TS_DEVICE,
    _TS_LSL,
    _TS_PARTICIPANT,
    _TS_SESSION,
    _TS_SITE,
    _TS_SPONSOR,
)


class TestMetadataIntegrity:
    """Every biosignal row must carry correct, non-null session metadata.

    Verifies that session_id, participant_id, site_id, sponsor_id, device_id,
    lsl_timestamp, and sample_index are all present and correct on every row.
    """

    @pytest.mark.parametrize("table", _BIOSIGNAL_TABLES)
    def test_rows_exist(self, cursor, biosignal_rows, table):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE session_id = %s",
            (_TS_SESSION,),
        )
        assert cursor.fetchone()[0] > 0, (
            f"{table}: no test rows found — fixture INSERT may have failed"
        )

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
        assert cursor.fetchone()[0] == 0, f"{table}: NULL found in a required metadata field"

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
        assert cursor.fetchone()[0] == 0, f"{table}: wrong lsl_timestamp value on some rows"
