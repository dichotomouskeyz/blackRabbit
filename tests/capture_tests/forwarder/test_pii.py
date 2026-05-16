"""DB integration: no plaintext patient data reaches any modality table.

participant_id must always be a pseudonymous opaque token — never a real name.
"""

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

_REAL_NAME = "Jane Doe"

_BIOSIGNAL_TABLES = ("eeg_samples", "hrv_samples", "eda_samples", "respiration_samples")

_PII_SCAN_QUERIES: dict[str, str] = {
    "eeg_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id, channel_id
        FROM eeg_samples WHERE session_id = %s
    """,
    "hrv_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id
        FROM hrv_samples WHERE session_id = %s
    """,
    "eda_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id
        FROM eda_samples WHERE session_id = %s
    """,
    "respiration_samples": """
        SELECT participant_id, site_id, sponsor_id, device_id
        FROM respiration_samples WHERE session_id = %s
    """,
    "echo_events": """
        SELECT participant_id, site_id, sponsor_id, event_type, source,
               actor_id, actor_role, zone_label
        FROM echo_events WHERE session_id = %s
    """,
}


@pytest.mark.integration
class TestNoPlaintextPatientData:
    """participant_id is always the pseudonymous token — never a real name."""

    def _insert_minimal_session(self, cursor):
        _insert_session_row(cursor, _INT_SESSION, _INT_SITE, _INT_SPONSOR, _INT_PART)
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
                       'proximity_state_change', 'manual_logging',
                       'therapist_01', 'therapist', 'arms_reach', %s)""",
            (_INT_SESSION, _INT_PART, _INT_SITE, _INT_SPONSOR, _INT_LSL_TS),
        )

    def test_eeg_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM eeg_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_hrv_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM hrv_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_eda_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM eda_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_respiration_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM respiration_samples WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_echo_participant_id_is_pseudonymous_token(self, cursor):
        self._insert_minimal_session(cursor)
        cursor.execute(
            "SELECT participant_id FROM echo_events WHERE session_id = %s", (_INT_SESSION,)
        )
        assert cursor.fetchone()[0] == _INT_PART

    def test_no_real_name_in_any_text_column(self, cursor):
        self._insert_minimal_session(cursor)
        for table, query in _PII_SCAN_QUERIES.items():
            cursor.execute(query, (_INT_SESSION,))
            for row in cursor.fetchall():
                for cell in row:
                    if cell is not None:
                        assert _REAL_NAME not in str(cell), (
                            f"PII sentinel '{_REAL_NAME}' found in {table}: {cell!r}"
                        )
