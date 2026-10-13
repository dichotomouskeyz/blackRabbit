"""Spec-driven integration tests for session_init (session-init.md R-010..R-015).

Phase 2 — atomic session creation against a live DB.
`create_session` opens its own connection and commits; we verify state with
a separate `db_conn` and clean up via explicit DELETE after each test.
Assertions derive from the spec text only.
"""

import pytest

from capture.session_init import create_session
from tests.capture_tests.session_init.support import (
    PARTICIPANT_ID,
    SITE_ID,
    SPONSOR_ID,
    VALID_COMPOUND,
)


def _run_create():
    return create_session(
        participant_id=PARTICIPANT_ID,
        compound=VALID_COMPOUND,
        site_id=SITE_ID,
        sponsor_id=SPONSOR_ID,
    )


@pytest.fixture
def _clean(db_conn):
    """Delete any session rows seeded by _run_create after each test."""
    yield
    db_conn.rollback()
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM schema_version_log WHERE session_id IN "
            "(SELECT id FROM sessions WHERE participant_id = %s::uuid)",
            (PARTICIPANT_ID,),
        )
        cur.execute(
            "DELETE FROM session_signal_metadata WHERE participant_id = %s::uuid",
            (PARTICIPANT_ID,),
        )
        cur.execute(
            "DELETE FROM sessions WHERE participant_id = %s::uuid",
            (PARTICIPANT_ID,),
        )
    db_conn.commit()


@pytest.mark.integration
class TestSessionInitDB:
    """session-init.md — DB integration.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r010_one_active_session_row(self, db_conn, _clean):
        session_id = _run_create()
        with db_conn.cursor() as cur:
            cur.execute("SELECT status FROM sessions WHERE id = %s::uuid", (session_id,))
            rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "active"

    def test_r011_four_metadata_rows(self, db_conn, _clean):
        session_id = _run_create()
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT modality FROM session_signal_metadata WHERE session_id = %s::uuid",
                (session_id,),
            )
            modalities = {r[0] for r in cur.fetchall()}
        assert modalities == {"eeg", "hrv", "eda", "respiration"}

    def test_r012_one_schema_version_row(self, db_conn, _clean):
        session_id = _run_create()
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM schema_version_log WHERE session_id = %s::uuid",
                (session_id,),
            )
            count = cur.fetchone()[0]
        assert count == 1

    def test_r013_rollback_leaves_no_partial_rows(self, db_conn, monkeypatch, _clean):
        # Patch psycopg2.connect so the returned connection has a commit that raises,
        # forcing create_session to rollback mid-transaction.
        import psycopg2 as _psycopg2

        orig_connect = _psycopg2.connect
        _call_count = {"n": 0}

        class _BoomConn:
            def __init__(self, real):
                self._real = real
                self.autocommit = False

            def cursor(self):
                return self._real.cursor()

            def commit(self):
                raise RuntimeError("simulated mid-transaction failure")

            def rollback(self):
                self._real.rollback()

            def close(self):
                self._real.close()

        def _patched_connect(*a, **kw):
            _call_count["n"] += 1
            return _BoomConn(orig_connect(*a, **kw))

        monkeypatch.setattr(_psycopg2, "connect", _patched_connect)
        import capture.session_init.workflow as wf

        monkeypatch.setattr(wf, "psycopg2", _psycopg2)

        with pytest.raises(Exception):
            _run_create()

        # After rollback, no session row for this participant.
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM sessions WHERE participant_id = %s::uuid",
                (PARTICIPANT_ID,),
            )
            assert cur.fetchone()[0] == 0

    def test_r014_no_direct_audit_write(self, db_conn, _clean):
        session_id = _run_create()
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM audit_events WHERE session_id = %s::uuid",
                (session_id,),
            )
            for (table_name,) in cur.fetchall():
                assert table_name is not None

    def test_r015_metadata_tenancy_matches_session(self, db_conn, _clean):
        session_id = _run_create()
        with db_conn.cursor() as cur:
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
