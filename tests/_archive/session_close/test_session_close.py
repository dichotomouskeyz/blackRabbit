"""Integration tests for capture.session_close."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg2
import pytest

import capture.session_close.workflow as session_close
from batch.arc.processor import ARCPostSessionError
from batch.reconcile import XDFTruncatedError
from config import settings

_SITE = "f1d00005-0000-4444-cccc-000000000001"
_SPONSOR = "f1d00005-0000-4444-dddd-000000000001"
_OTHER_SPONSOR = "f1d00005-0000-4444-dddd-000000000099"
_PART = "f1d00005-0000-4444-bbbb-000000000001"
_COMPOUND = "psilocybin"

_MATCHED = {"EEG": 10, "HRV": 5, "EDA": 8, "Respiration": 6}

_FAKE_XDF = Path("/fake/session.xdf")


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
    cur.execute("DELETE FROM biosignal_integrity_log WHERE session_id = %s", (session_id,))
    cur.execute("DELETE FROM alert_events WHERE session_id = %s", (session_id,))
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


def _get_integrity_log_types(db_url: str, session_id: str) -> list[str]:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT log_type FROM biosignal_integrity_log WHERE session_id = %s ORDER BY id",
        (session_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


def _get_alert_rows(db_url: str, session_id: str) -> list[tuple]:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT alert_type, algorithm_name, algorithm_version, algorithm_parameters,
               severity, message
        FROM alert_events
        WHERE session_id = %s
        ORDER BY id
        """,
        (session_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _run(
    session_id: str,
    db_url: str,
    sponsor_id: str = _SPONSOR,
    xdf_counts: dict | None = None,
    db_counts: dict | None = None,
) -> int:
    xdf = xdf_counts if xdf_counts is not None else _MATCHED
    dbc = db_counts if db_counts is not None else _MATCHED
    with (
        patch("capture.session_close.reconciliation.read_xdf_counts", return_value=xdf),
        patch("capture.session_close.reconciliation.query_db_counts", return_value=dbc),
        patch.object(settings, "DATABASE_URL", db_url),
    ):
        return session_close.run(session_id, sponsor_id, _FAKE_XDF)


@pytest.mark.integration
class TestSessionClose:
    def test_close_reconciled_session(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000001"
        _insert_session(db_url, sid)
        try:
            code = _run(sid, db_url)

            assert code == 0
            assert _get_status(db_url, sid) == "closed"
            assert "watermark_verified" in _get_audit_types(db_url, sid)
            assert _get_integrity_log_types(db_url, sid) == ["xdf_reconciliation"]
        finally:
            _cleanup(db_url, sid)

    def test_close_failed_session(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000002"
        _insert_session(db_url, sid)
        try:
            code = _run(
                sid,
                db_url,
                xdf_counts={"EEG": 10},
                db_counts={"EEG": 15},
            )

            assert code == 1
            assert _get_status(db_url, sid) == "failed"
            assert "watermark_failed" in _get_audit_types(db_url, sid)
            assert _get_integrity_log_types(db_url, sid) == ["xdf_reconciliation"]
        finally:
            _cleanup(db_url, sid)

    def test_session_not_found(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000099"
        code = _run(sid, db_url)

        assert code == 2
        assert _get_status(db_url, sid) is None

    def test_wrong_sponsor_is_not_closeable(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000109"
        _insert_session(db_url, sid)
        try:
            code = _run(sid, db_url, sponsor_id=_OTHER_SPONSOR)

            assert code == 2
            assert _get_status(db_url, sid) == "active"
        finally:
            _cleanup(db_url, sid)

    def test_session_wrong_state(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000003"
        _insert_session(db_url, sid, status="initializing")
        try:
            code = _run(sid, db_url)

            assert code == 2
            assert _get_status(db_url, sid) == "initializing"
        finally:
            _cleanup(db_url, sid)

    def test_idempotent_from_closing(self, db_url):
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
        sid = "f1d00005-0000-4444-aaaa-000000000005"
        _insert_session(db_url, sid)
        try:
            with (
                patch(
                    "capture.session_close.reconciliation.read_xdf_counts",
                    side_effect=XDFTruncatedError("footer missing"),
                ),
                patch.object(settings, "DATABASE_URL", db_url),
            ):
                code = session_close.run(sid, _SPONSOR, _FAKE_XDF)

            assert code == 2
            assert _get_status(db_url, sid) == "active"
        finally:
            _cleanup(db_url, sid)

    def test_watermark_not_written_twice(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000006"
        _insert_session(db_url, sid)
        try:
            _run(sid, db_url)
            audit_types = _get_audit_types(db_url, sid)
            watermark_events = [e for e in audit_types if e == "watermark_verified"]
            assert len(watermark_events) == 1
        finally:
            _cleanup(db_url, sid)

    def test_arc_post_session_is_invoked(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000007"
        _insert_session(db_url, sid)
        try:
            with (
                patch(
                    "capture.session_close.reconciliation.read_xdf_counts",
                    return_value=_MATCHED,
                ),
                patch(
                    "capture.session_close.reconciliation.query_db_counts",
                    return_value=_MATCHED,
                ),
                patch("capture.session_close.workflow.run_arc_post_session") as arc_mock,
                patch.object(settings, "DATABASE_URL", db_url),
            ):
                arc_mock.return_value = SimpleNamespace(
                    session_id=sid,
                    canonical_anchor_count=1,
                    cluster_count=1,
                    baseline_row_count=4,
                    baseline_window_start=100.0,
                    baseline_window_end=220.0,
                )
                code = session_close.run(sid, _SPONSOR, _FAKE_XDF)

            assert code == 0
            assert arc_mock.call_count == 1
            assert arc_mock.call_args.args[1] == sid
            assert _get_status(db_url, sid) == "closed"
        finally:
            _cleanup(db_url, sid)

    def test_arc_post_session_failure_marks_session_failed(self, db_url):
        sid = "f1d00005-0000-4444-aaaa-000000000008"
        _insert_session(db_url, sid)
        try:
            with (
                patch(
                    "capture.session_close.reconciliation.read_xdf_counts",
                    return_value=_MATCHED,
                ),
                patch(
                    "capture.session_close.reconciliation.query_db_counts",
                    return_value=_MATCHED,
                ),
                patch(
                    "capture.session_close.workflow.run_arc_post_session",
                    side_effect=ARCPostSessionError("boom"),
                ),
                patch.object(settings, "DATABASE_URL", db_url),
            ):
                code = session_close.run(sid, _SPONSOR, _FAKE_XDF)

            assert code == 1
            assert _get_status(db_url, sid) == "failed"
            assert "watermark_failed" in _get_audit_types(db_url, sid)
            alert_rows = _get_alert_rows(db_url, sid)
            assert len(alert_rows) == 1
            assert alert_rows[0][0] == "arc_failure"
            assert alert_rows[0][1] == "arc_post_session"
            assert alert_rows[0][4] == "critical"
        finally:
            _cleanup(db_url, sid)
