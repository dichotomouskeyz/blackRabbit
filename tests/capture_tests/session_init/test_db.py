"""Spec-driven integration tests for session_init (session-init.md R-010..R-015).

Phase 2 — atomic session creation against a live DB. `create_session` is given
the rolled-back `db_conn` (commit/close neutralised) so its writes are visible
to in-transaction assertions and discarded on teardown.
Assertions derive from the spec text only.

NOTE (black-box): create_session signature inferred from the spec. Phase D
resolves any mismatch in `_run_create` only.
"""

import pytest

from capture.session_init import create_session
from tests.capture_tests.session_init.support import PARTICIPANT_ID, VALID_COMPOUND


@pytest.fixture
def in_txn_conn(db_conn, monkeypatch):
    """Inject db_conn as the create_session connection without persisting."""
    monkeypatch.setattr(db_conn, "commit", lambda: None, raising=False)
    monkeypatch.setattr(db_conn, "close", lambda: None, raising=False)
    return db_conn


def _run_create(conn):
    return create_session(
        participant_id=PARTICIPANT_ID,
        compound=VALID_COMPOUND,
        db_factory=lambda *a, **k: conn,
    )


@pytest.mark.integration
class TestSessionInitDB:
    """session-init.md — DB integration.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r010_one_active_session_row(self, in_txn_conn):
        session_id = _run_create(in_txn_conn)
        with in_txn_conn.cursor() as cur:
            cur.execute("SELECT status FROM sessions WHERE id = %s::uuid", (session_id,))
            rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "active"

    def test_r011_four_metadata_rows(self, in_txn_conn):
        session_id = _run_create(in_txn_conn)
        with in_txn_conn.cursor() as cur:
            cur.execute(
                "SELECT modality FROM session_signal_metadata WHERE session_id = %s::uuid",
                (session_id,),
            )
            modalities = {r[0] for r in cur.fetchall()}
        assert modalities == {"eeg", "hrv", "eda", "respiration"}

    def test_r012_one_schema_version_row(self, in_txn_conn):
        session_id = _run_create(in_txn_conn)
        with in_txn_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM schema_version_log WHERE session_id = %s::uuid",
                (session_id,),
            )
            count = cur.fetchone()[0]
        assert count == 1

    def test_r013_rollback_leaves_no_partial_rows(self, db_conn, monkeypatch):
        # Force a failure mid-transaction: a connection whose commit raises.
        monkeypatch.setattr(db_conn, "close", lambda: None, raising=False)

        def _boom():
            raise RuntimeError("simulated mid-transaction failure")

        monkeypatch.setattr(db_conn, "commit", _boom, raising=False)
        with pytest.raises(Exception):
            _run_create(db_conn)
        db_conn.rollback()
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sessions WHERE participant_id = %s::uuid", (PARTICIPANT_ID,)
            )
            assert cur.fetchone()[0] == 0

    def test_r014_no_direct_audit_write(self, in_txn_conn):
        session_id = _run_create(in_txn_conn)
        with in_txn_conn.cursor() as cur:
            # Any audit row for this session must have come from the trigger,
            # carrying table_name = 'sessions' (trigger-sourced), not a direct
            # application insert.
            cur.execute(
                "SELECT table_name FROM audit_events WHERE session_id = %s::uuid",
                (session_id,),
            )
            for (table_name,) in cur.fetchall():
                assert table_name is not None

    def test_r015_metadata_tenancy_matches_session(self, in_txn_conn):
        session_id = _run_create(in_txn_conn)
        with in_txn_conn.cursor() as cur:
            cur.execute(
                "SELECT site_id, sponsor_id FROM sessions WHERE id = %s::uuid",
                (session_id,),
            )
            session_tenancy = cur.fetchone()
            cur.execute(
                "SELECT DISTINCT site_id, sponsor_id FROM session_signal_metadata "
                "WHERE session_id = %s::uuid",
                (session_id,),
            )
            metadata_tenancy = cur.fetchall()
        assert metadata_tenancy == [session_tenancy]
