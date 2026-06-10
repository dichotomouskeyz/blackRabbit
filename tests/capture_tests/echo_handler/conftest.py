"""Seed fixture for ECHO handler integration tests."""

import pytest

from tests.capture_tests.echo_handler.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


@pytest.fixture
def seeded_session(cursor, db_conn):
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
    return {"session_id": SESSION_ID}
