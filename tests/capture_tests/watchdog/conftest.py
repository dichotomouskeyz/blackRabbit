"""Seed fixture for watchdog DB integration tests."""

import pytest

from tests.capture_tests.watchdog.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


@pytest.fixture
def seeded_active_session(cursor, db_conn):
    cursor.execute(
        """
        INSERT INTO sessions
            (id, site_id, sponsor_id, participant_id, capture_source,
             compound, status, started_at)
        VALUES
            (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'simulated',
             'psilocybin', 'active'::session_status, NOW())
        """,
        (SESSION_ID, SITE_ID, SPONSOR_ID, PARTICIPANT_ID),
    )
    db_conn.commit()
    return {
        "session_id": SESSION_ID,
        "participant_id": PARTICIPANT_ID,
        "site_id": SITE_ID,
        "sponsor_id": SPONSOR_ID,
    }
