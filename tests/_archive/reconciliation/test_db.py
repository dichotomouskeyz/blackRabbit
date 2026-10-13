"""DB integration tests for query_db_counts."""

import pytest

from batch.reconcile import query_db_counts
from tests.capture_tests.reconciliation.support import (
    _ALL_STREAMS,
    _REC_DEVICE,
    _REC_LSL,
    _REC_PARTICIPANT,
    _REC_SESSION,
    _REC_SITE,
    _REC_SPONSOR,
)


@pytest.mark.integration
class TestQueryDBCounts:
    def test_zero_counts_for_unknown_session(self, db_conn):
        fake_session = "00000000-0000-0000-0000-000000000099"
        counts = query_db_counts(db_conn, fake_session)
        for name in _ALL_STREAMS:
            assert counts[name] == 0

    def test_counts_reflect_inserted_samples(self, cursor, db_conn):
        cursor.execute(
            """
            INSERT INTO sessions (
                id, site_id, sponsor_id, participant_id,
                compound, status, started_at
            ) VALUES (
                %s, %s, %s, %s, 'psilocybin', 'active', NOW()
            ) ON CONFLICT (id) DO NOTHING
            """,
            (_REC_SESSION, _REC_SITE, _REC_SPONSOR, _REC_PARTICIPANT),
        )

        cursor.execute(
            """INSERT INTO eeg_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 channel_id, voltage, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 'ch_0', 1.0, %s, 0)""",
            (_REC_SESSION, _REC_PARTICIPANT, _REC_SITE, _REC_SPONSOR, _REC_DEVICE, _REC_LSL),
        )
        cursor.execute(
            """INSERT INTO hrv_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 rr_interval_ms, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 860.0, %s, 0)""",
            (_REC_SESSION, _REC_PARTICIPANT, _REC_SITE, _REC_SPONSOR, _REC_DEVICE, _REC_LSL),
        )
        cursor.execute(
            """INSERT INTO eda_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 raw_conductance_us, conductance_us, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 5.0, 5.0, %s, 0)""",
            (_REC_SESSION, _REC_PARTICIPANT, _REC_SITE, _REC_SPONSOR, _REC_DEVICE, _REC_LSL),
        )
        cursor.execute(
            """INSERT INTO respiration_samples
                (session_id, participant_id, site_id, sponsor_id, device_id,
                 raw_amplitude, processed_amplitude, lsl_timestamp, sample_index)
               VALUES (%s, %s, %s, %s, %s, 0.5, 0.5, %s, 0)""",
            (_REC_SESSION, _REC_PARTICIPANT, _REC_SITE, _REC_SPONSOR, _REC_DEVICE, _REC_LSL),
        )
        db_conn.commit()

        counts = query_db_counts(db_conn, _REC_SESSION)
        assert counts["EEG"] == 1
        assert counts["HRV"] == 1
        assert counts["EDA"] == 1
        assert counts["Respiration"] == 1
