"""DB integration: lsl_timestamp and db_insert_time are always distinct.

After inserting one row into each of the 5 modality tables we SELECT both
timestamp columns back and assert lsl_timestamp is the float we sent and
db_insert_time is a server-generated timestamptz — provably independent.
"""

import datetime

import pytest

from tests.capture_tests.forwarder.support import (
    _INT_DEVICE,
    _INT_LSL_TS,
    _INT_PART,
    _INT_SESSION,
    _INT_SITE,
    _INT_SPONSOR,
    _insert_session_row,
)


@pytest.mark.integration
class TestSeparateTimestampsDB:
    """lsl_timestamp (float) and db_insert_time (timestamptz) are always distinct."""

    def _insert_one_sample_each(self, cursor):
        cursor.execute(
            """INSERT INTO eeg_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                channel_id, voltage, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 'ch_0', 1.0, %s, 0)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_DEVICE, _INT_LSL_TS),
        )
        cursor.execute(
            """INSERT INTO hrv_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                rr_interval_ms, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 860.0, %s, 0)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_DEVICE, _INT_LSL_TS),
        )
        cursor.execute(
            """INSERT INTO eda_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, 0)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_DEVICE, _INT_LSL_TS),
        )
        cursor.execute(
            """INSERT INTO respiration_samples
               (session_id, participant_id, site_id, sponsor_id, device_id,
                raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, 0)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_DEVICE, _INT_LSL_TS),
        )
        cursor.execute(
            """INSERT INTO echo_events
               (session_id, participant_id, site_id, sponsor_id,
                event_type, source, actor_id, actor_role, zone_label, lsl_timestamp)
               VALUES (%s, %s, %s, %s,
                       'zone_enter', 'manual_logging',
                       'therapist_01', 'therapist', 'arms_reach', %s)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_LSL_TS),
        )

    def test_eeg_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM eeg_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_eeg_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM eeg_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_hrv_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM hrv_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_hrv_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM hrv_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_eda_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM eda_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_eda_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM eda_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_respiration_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM respiration_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_respiration_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM respiration_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)

    def test_echo_lsl_timestamp_stored_correctly(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT lsl_timestamp FROM echo_events WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == pytest.approx(_INT_LSL_TS)

    def test_echo_db_insert_time_is_datetime(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
        self._insert_one_sample_each(cursor)
        cursor.execute(
            "SELECT db_insert_time FROM echo_events WHERE session_id = %s", (_INT_SESSION,)
        )
        stored = cursor.fetchone()[0]
        assert stored is not None
        assert isinstance(stored, datetime.datetime)
