import pytest

from tests.capture_tests.schema.support import (
    _TS_DEVICE,
    _TS_LSL,
    _TS_PARTICIPANT,
    _TS_SESSION,
    _TS_SITE,
    _TS_SPONSOR,
)


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
