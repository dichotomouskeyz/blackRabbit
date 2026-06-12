"""Seed fixture for reconciliation DB integration tests."""

import pytest

from tests.capture_tests.reconciliation.support import (
    DEVICE_ID,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


@pytest.fixture
def seeded_recon_session(cursor, db_conn):
    cursor.execute(
        """
        INSERT INTO sessions
            (id, site_id, sponsor_id, participant_id, capture_source,
             compound, status, started_at)
        VALUES
            (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'simulated',
             'psilocybin', 'closing'::session_status, NOW())
        """,
        (SESSION_ID, SITE_ID, SPONSOR_ID, PARTICIPANT_ID),
    )
    for idx in range(3):
        cursor.execute(
            """
            INSERT INTO eeg_samples
                (id, session_id, participant_id, site_id, sponsor_id, device_id,
                 lsl_timestamp, db_insert_time, sample_index, channel_id, voltage)
            VALUES
                (gen_random_uuid(), %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                 %s, NOW(), %s, 'ch_0', 1.0)
            """,
            (SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID, DEVICE_ID, 1000.0 + idx, idx),
        )
    db_conn.commit()
    yield {
        "session_id": SESSION_ID,
        "participant_id": PARTICIPANT_ID,
        "site_id": SITE_ID,
        "sponsor_id": SPONSOR_ID,
        "device_id": DEVICE_ID,
        "eeg_count": 3,
    }
    db_conn.rollback()  # clear any aborted transaction left by the test
    cursor.execute("DELETE FROM eeg_samples WHERE session_id = %s::uuid", (SESSION_ID,))
    cursor.execute("DELETE FROM biosignal_integrity_log WHERE session_id = %s::uuid", (SESSION_ID,))
    cursor.execute("DELETE FROM sessions WHERE id = %s::uuid", (SESSION_ID,))
    db_conn.commit()
