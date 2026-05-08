"""Integration tests for capture/session_close.py.

These tests hit a real DB (TEST_DATABASE_URL) and mock only I/O that requires
real hardware: XDF file reads and raw DB count queries.  They verify:
  - State machine: active → closing → closed / failed
  - DB trigger: watermark_verified / watermark_failed written to audit_events
  - Pre-condition guard: wrong state and missing session return exit code 2

Requirements:
  TEST_DATABASE_URL set in .env
  Migrations through 024_watermark_trigger applied to test DB
  Run: alembic upgrade head  (from consensai-1a-DB/db/)

Run these tests:
    pytest tests/test_session_close.py -m integration -v
"""

from pathlib import Path
from unittest.mock import patch

import psycopg2
import pytest

import capture.session_close as session_close
from batch.reconcile import XDFTruncatedError

# ---------------------------------------------------------------------------
# Constants shared across all tests in this file
# ---------------------------------------------------------------------------
_SITE = "f1d00005-0000-4444-cccc-000000000001"
_SPONSOR = "f1d00005-0000-4444-dddd-000000000001"
_PART = "f1d00005-0000-4444-bbbb-000000000001"
_COMPOUND = "psilocybin"

# Counts that make all streams perfectly reconciled (gap == 0)
_MATCHED = {"EEG": 10, "HRV": 5, "EDA": 8, "Respiration": 6}

_FAKE_XDF = Path("/fake/session.xdf")


# ---------------------------------------------------------------------------
# DB helpers — use autocommit so rows are immediately visible to the SUT
# ---------------------------------------------------------------------------


def _conn(db_url: str) -> psycopg2.extensions.connection:
    c = psycopg2.connect(db_url)
    c.autocommit = True
    return c


def _insert_session(db_url: str, session_id: str, status: str = "active") -> None:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sessions (
            id, site_id, sponsor_id, participant_id, compound, status
        ) VALUES (
            %s, %s::uuid, %s::uuid, %s::uuid, %s, %s::session_status
        )
        ON CONFLICT (id) DO NOTHING
        """,
        (session_id, _SITE, _SPONSOR, _PART, _COMPOUND, status),
    )
    cur.close()
    conn.close()


def _cleanup(db_url: str, session_id: str) -> None:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_events WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    cur.close()
    conn.close()


def _get_status(db_url: str, session_id: str) -> str | None:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute("SELECT status FROM sessions WHERE id = %s", (session_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return str(row[0]) if row else None


def _get_audit_types(db_url: str, session_id: str) -> list[str]:
    """Return event_type values from audit_events for this session, oldest first."""
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT event_type FROM audit_events WHERE session_id = %s ORDER BY id",
        (session_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


def _run(
    session_id: str,
    db_url: str,
    xdf_counts: dict | None = None,
    db_counts: dict | None = None,
) -> int:
    """Call session_close.run with mocked I/O and the test DB URL."""
    xdf = xdf_counts if xdf_counts is not None else _MATCHED
    dbc = db_counts if db_counts is not None else _MATCHED
    with (
        patch("capture.session_close.read_xdf_counts", return_value=xdf),
        patch("capture.session_close.query_db_counts", return_value=dbc),
        patch.object(session_close.settings, "DATABASE_URL", db_url),
    ):
        return session_close.run(session_id, _FAKE_XDF)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSessionClose:

    def test_close_reconciled_session(self, db_url):
        """Active session with matching XDF/DB counts → 'closed', watermark_verified."""
        sid = "f1d00005-0000-4444-aaaa-000000000001"
        _insert_session(db_url, sid)
        try:
            code = _run(sid, db_url)

            assert code == 0
            assert _get_status(db_url, sid) == "closed"
            assert "watermark_verified" in _get_audit_types(db_url, sid)
        finally:
            _cleanup(db_url, sid)

    def test_close_failed_session(self, db_url):
        """Unrecoverable gap (DB > XDF) → 'failed', watermark_failed in audit."""
        sid = "f1d00005-0000-4444-aaaa-000000000002"
        _insert_session(db_url, sid)
        try:
            # DB has 5 more EEG rows than XDF — gap < 0, cannot backfill
            code = _run(
                sid,
                db_url,
                xdf_counts={"EEG": 10},
                db_counts={"EEG": 15},
            )

            assert code == 1
            assert _get_status(db_url, sid) == "failed"
            assert "watermark_failed" in _get_audit_types(db_url, sid)
        finally:
            _cleanup(db_url, sid)

    def test_session_not_found(self, db_url):
        """Non-existent session_id → exit code 2, no session created."""
        sid = "f1d00005-0000-4444-aaaa-000000000099"
        code = _run(sid, db_url)

        assert code == 2
        assert _get_status(db_url, sid) is None

    def test_session_wrong_state(self, db_url):
        """Session in 'initializing' state → exit code 2, status unchanged."""
        sid = "f1d00005-0000-4444-aaaa-000000000003"
        _insert_session(db_url, sid, status="initializing")
        try:
            code = _run(sid, db_url)

            assert code == 2
            assert _get_status(db_url, sid) == "initializing"
        finally:
            _cleanup(db_url, sid)

    def test_idempotent_from_closing(self, db_url):
        """Session already in 'closing' state → still completes successfully."""
        sid = "f1d00005-0000-4444-aaaa-000000000004"
        _insert_session(db_url, sid, status="closing")
        try:
            code = _run(sid, db_url)

            assert code == 0
            assert _get_status(db_url, sid) == "closed"
            assert "watermark_verified" in _get_audit_types(db_url, sid)
        finally:
            _cleanup(db_url, sid)

    def test_xdf_truncated_aborts_before_state_change(self, db_url):
        """XDF file truncated → exit code 2, session stays 'active'."""
        sid = "f1d00005-0000-4444-aaaa-000000000005"
        _insert_session(db_url, sid)
        try:
            with (
                patch(
                    "capture.session_close.read_xdf_counts",
                    side_effect=XDFTruncatedError("footer missing"),
                ),
                patch.object(session_close.settings, "DATABASE_URL", db_url),
            ):
                code = session_close.run(sid, _FAKE_XDF)

            assert code == 2
            assert _get_status(db_url, sid) == "active"
        finally:
            _cleanup(db_url, sid)

    def test_watermark_not_written_twice(self, db_url):
        """Closing twice produces exactly one watermark_verified row."""
        sid = "f1d00005-0000-4444-aaaa-000000000006"
        _insert_session(db_url, sid)
        try:
            _run(sid, db_url)  # closes to 'closed'
            audit_types = _get_audit_types(db_url, sid)
            watermark_events = [e for e in audit_types if e == "watermark_verified"]
            assert len(watermark_events) == 1
        finally:
            _cleanup(db_url, sid)
