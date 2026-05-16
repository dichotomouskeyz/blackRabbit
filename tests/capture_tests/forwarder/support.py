"""Shared constants and helpers for forwarder test modules."""

from capture.forwarder import SessionConfig

# Unit-test config — no DB involved
_UNIT_CFG = SessionConfig(
    session_id="aa000001-0000-4444-0000-000000000001",
    participant_id="aa000001-0000-4444-bbbb-000000000001",
    site_id="aa000001-0000-4444-cccc-000000000001",
    sponsor_id="aa000001-0000-4444-dddd-000000000001",
)
_UNIT_LSL_TS = 123456.789

# Integration-test identifiers (distinct from reconciliation test IDs)
_INT_SESSION = "f1d00001-0000-4444-aaaa-000000000001"
_INT_PART = "f1d00001-0000-4444-bbbb-000000000001"
_INT_SITE = "f1d00001-0000-4444-cccc-000000000001"
_INT_SPONSOR = "f1d00001-0000-4444-dddd-000000000001"
_INT_DEVICE = "f1d00001-0000-4444-eeee-000000000001"
_INT_LSL_TS = 777777.111


def _insert_session_row(cursor, session_id, site_id, sponsor_id, participant_id):
    cursor.execute(
        """
        INSERT INTO sessions (id, site_id, sponsor_id, participant_id,
                              compound, status, started_at)
        VALUES (%s, %s, %s, %s, 'psilocybin', 'active', NOW())
        ON CONFLICT (id) DO NOTHING
        """,
        (session_id, site_id, sponsor_id, participant_id),
    )
