"""Tests for capture.watchdog — simulated crash and audit trail verification.

Every time lsl_forwarder exits unexpectedly, watchdog calls _log_restart(),
which inserts into alert_events. The audit trigger on alert_events automatically
writes a corresponding row to audit_events. These tests confirm that entire chain.

Three levels of coverage:
  1. _log_restart writes a well-formed alert_events row.
  2. _log_restart triggers an audit_events entry (DB trigger verification).
  3. End-to-end: main() with a mocked crashing subprocess produces both rows.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import capture.watchdog as watchdog_module  # noqa: E402


def _direct_conn():
    """Open a fresh psycopg2 connection to the test DB."""
    url = os.getenv("TEST_DATABASE_URL", "")
    url = url.replace("postgresql://", "")
    user_pass, rest = url.split("@")
    user, password = user_pass.split(":")
    host_port, dbname = rest.split("/")
    host, port = host_port.split(":")
    return psycopg2.connect(
        host=host, port=int(port), dbname=dbname, user=user, password=password
    )


# Unique session IDs that don't collide with test_schema.py fixtures
_SID_ALERT = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a01"
_SID_AUDIT = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a02"
_SID_E2E = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a03"


class TestWatchdogAuditTrail:
    """Verify every watchdog process_restart is logged to both alert_events and audit_events."""

    def test_log_restart_writes_alert_event(self, monkeypatch):
        """_log_restart inserts a process_restart row with all required governance columns."""
        monkeypatch.setattr(
            watchdog_module.settings,
            "DATABASE_URL",
            os.getenv("TEST_DATABASE_URL"),
        )
        _insert_session(_SID_ALERT)
        try:
            watchdog_module._log_restart(
                session_id=_SID_ALERT,
                participant_id="aaaa0003-0000-0000-0000-000000000001",
                site_id="bbbb0000-0000-0000-0000-000000000001",
                sponsor_id="cccc0000-0000-0000-0000-000000000001",
                exit_code=1,
                restart_count=1,
                uptime_s=12.5,
            )

            conn = _direct_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT alert_type, algorithm_name, algorithm_version,
                               algorithm_parameters, severity
                        FROM alert_events
                        WHERE session_id = %s AND alert_type = 'process_restart'
                        ORDER BY db_insert_time DESC LIMIT 1
                        """,
                        (_SID_ALERT,),
                    )
                    row = cur.fetchone()
            finally:
                conn.close()
        finally:
            _cleanup_session(_SID_ALERT)

        assert row is not None, "No process_restart row found in alert_events"
        assert row[0] == "process_restart"
        assert row[1] == "watchdog"
        assert row[2] == "1.0.0"
        assert row[3]["exit_code"] == 1
        assert row[3]["restart_count"] == 1
        assert row[3]["uptime_s"] == 12.5
        assert row[4] == "warning"

    def test_log_restart_triggers_audit_event(self, monkeypatch):
        """The audit trigger fires on every alert_events INSERT — no application code needed."""
        monkeypatch.setattr(
            watchdog_module.settings,
            "DATABASE_URL",
            os.getenv("TEST_DATABASE_URL"),
        )
        _insert_session(_SID_AUDIT)
        try:
            watchdog_module._log_restart(
                session_id=_SID_AUDIT,
                participant_id="aaaa0003-0000-0000-0000-000000000002",
                site_id="bbbb0000-0000-0000-0000-000000000001",
                sponsor_id="cccc0000-0000-0000-0000-000000000001",
                exit_code=137,
                restart_count=2,
                uptime_s=300.0,
            )

            conn = _direct_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM audit_events
                        WHERE session_id = %s AND table_name = 'alert_events'
                        """,
                        (_SID_AUDIT,),
                    )
                    count = cur.fetchone()[0]
            finally:
                conn.close()
        finally:
            _cleanup_session(_SID_AUDIT)

        assert count >= 1, "Audit trigger did not fire on process_restart INSERT"

    def test_simulated_crash_end_to_end(self, monkeypatch):
        """Run main() with a subprocess that crashes — confirm the full chain fires.

        Chain: forwarder exits → _log_restart() → alert_events INSERT
               → audit trigger → audit_events INSERT
        """
        monkeypatch.setattr(
            watchdog_module.settings,
            "DATABASE_URL",
            os.getenv("TEST_DATABASE_URL"),
        )
        monkeypatch.setattr(watchdog_module, "MAX_RESTARTS", 1)
        monkeypatch.setattr(watchdog_module, "RESTART_DELAY_BASE_S", 0.0)
        _insert_session(_SID_E2E)
        try:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.wait.return_value = None
            mock_proc.returncode = 1

            monkeypatch.setattr(
                sys,
                "argv",
                [
                    "watchdog",
                    "--session-id",
                    _SID_E2E,
                    "--participant-id",
                    "aaaa0003-0000-0000-0000-000000000003",
                    "--site-id",
                    "bbbb0000-0000-0000-0000-000000000001",
                    "--sponsor-id",
                    "cccc0000-0000-0000-0000-000000000001",
                ],
            )

            with patch("capture.watchdog.subprocess.Popen", return_value=mock_proc):
                with patch("capture.watchdog.time.sleep"):
                    watchdog_module.main()

            conn = _direct_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT algorithm_name, algorithm_parameters
                        FROM alert_events
                        WHERE session_id = %s AND alert_type = 'process_restart'
                        ORDER BY db_insert_time DESC LIMIT 1
                        """,
                        (_SID_E2E,),
                    )
                    alert_row = cur.fetchone()

                    cur.execute(
                        """
                        SELECT COUNT(*) FROM audit_events
                        WHERE session_id = %s AND table_name = 'alert_events'
                        """,
                        (_SID_E2E,),
                    )
                    audit_count = cur.fetchone()[0]
            finally:
                conn.close()
        finally:
            _cleanup_session(_SID_E2E)

        assert alert_row is not None, "main() did not write a process_restart alert"
        assert alert_row[0] == "watchdog"
        assert alert_row[1]["exit_code"] == 1
        assert audit_count >= 1, "Audit trigger did not fire during simulated crash"


# ---------------------------------------------------------------------------
# Helpers for session-state tests
# ---------------------------------------------------------------------------

_SITE_UUID = "f1d00009-0000-4444-cccc-000000000001"
_SPONSOR_UUID = "f1d00009-0000-4444-dddd-000000000001"
_PART_UUID = "f1d00009-0000-4444-bbbb-000000000001"

_SID_CLOSING = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a04"
_SID_FAILED = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a05"
_SID_MAXRETRY = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a06"
_SID_NOOP_CLOSING = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a07"
_SID_NOOP_CLOSED = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a08"


def _insert_session(session_id: str, status: str = "active") -> None:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (id, site_id, sponsor_id, participant_id,
                                  compound, status)
            VALUES (%s, %s::uuid, %s::uuid, %s::uuid,
                    'psilocybin', %s::session_status)
            ON CONFLICT (id) DO NOTHING
            """,
            (session_id, _SITE_UUID, _SPONSOR_UUID, _PART_UUID, status),
        )
    conn.close()


def _cleanup_session(session_id: str) -> None:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DELETE FROM audit_events WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM alert_events WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    conn.close()


def _get_status(session_id: str) -> str | None:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
    conn.close()
    return str(row[0]) if row else None


def _get_audit_types(session_id: str) -> list[str]:
    conn = _direct_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_type FROM audit_events WHERE session_id = %s ORDER BY id",
            (session_id,),
        )
        rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Session-state transition tests
# ---------------------------------------------------------------------------


class TestWatchdogSessionTransitions:
    """Verify _mark_session_closing and _mark_session_failed update state correctly."""

    def test_mark_session_closing_sets_status(self, monkeypatch):
        """Clean shutdown: active → closing, no watermark event written."""
        monkeypatch.setattr(
            watchdog_module.settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_CLOSING, status="active")
        try:
            watchdog_module._mark_session_closing(_SID_CLOSING)

            assert _get_status(_SID_CLOSING) == "closing"
            assert "watermark_verified" not in _get_audit_types(_SID_CLOSING)
            assert "watermark_failed" not in _get_audit_types(_SID_CLOSING)
        finally:
            _cleanup_session(_SID_CLOSING)

    def test_mark_session_closing_is_noop_if_already_closing(self, monkeypatch):
        """Calling _mark_session_closing twice is safe — WHERE status='active' is a no-op."""
        monkeypatch.setattr(
            watchdog_module.settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_NOOP_CLOSING, status="closing")
        try:
            watchdog_module._mark_session_closing(_SID_NOOP_CLOSING)

            assert _get_status(_SID_NOOP_CLOSING) == "closing"
        finally:
            _cleanup_session(_SID_NOOP_CLOSING)

    def test_mark_session_failed_sets_status_and_fires_trigger(self, monkeypatch):
        """Max restarts: active → failed, watermark_failed written to audit_events."""
        monkeypatch.setattr(
            watchdog_module.settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_FAILED, status="active")
        try:
            watchdog_module._mark_session_failed(_SID_FAILED)

            assert _get_status(_SID_FAILED) == "failed"
            assert "watermark_failed" in _get_audit_types(_SID_FAILED)
        finally:
            _cleanup_session(_SID_FAILED)

    def test_mark_session_failed_is_noop_on_closed_session(self, monkeypatch):
        """If the session is already 'closed', _mark_session_failed does not overwrite it."""
        monkeypatch.setattr(
            watchdog_module.settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_NOOP_CLOSED, status="closed")
        try:
            watchdog_module._mark_session_failed(_SID_NOOP_CLOSED)

            assert _get_status(_SID_NOOP_CLOSED) == "closed"
        finally:
            _cleanup_session(_SID_NOOP_CLOSED)

    def test_max_restarts_marks_session_failed_end_to_end(self, monkeypatch):
        """main() exhausting MAX_RESTARTS writes process_restart alerts and marks session failed."""
        monkeypatch.setattr(
            watchdog_module.settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        monkeypatch.setattr(watchdog_module, "MAX_RESTARTS", 1)
        monkeypatch.setattr(watchdog_module, "RESTART_DELAY_BASE_S", 0.0)

        _insert_session(_SID_MAXRETRY, status="active")

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "watchdog",
                "--session-id",
                _SID_MAXRETRY,
                "--participant-id",
                _PART_UUID,
                "--site-id",
                _SITE_UUID,
                "--sponsor-id",
                _SPONSOR_UUID,
            ],
        )

        try:
            with patch("capture.watchdog.subprocess.Popen", return_value=mock_proc):
                with patch("capture.watchdog.time.sleep"):
                    watchdog_module.main()

            assert (
                _get_status(_SID_MAXRETRY) == "failed"
            ), "session should be 'failed' after max restarts exhausted"
            assert "watermark_failed" in _get_audit_types(
                _SID_MAXRETRY
            ), "watermark_failed must be written to audit_events"

            # Every crash (including the final one) must be logged to alert_events
            conn = _direct_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM alert_events "
                        "WHERE session_id = %s AND alert_type = 'process_restart'",
                        (_SID_MAXRETRY,),
                    )
                    alert_count = cur.fetchone()[0]
            finally:
                conn.close()

            # MAX_RESTARTS=1 → forwarder crashes twice → 2 alert_events rows
            assert (
                alert_count == 2
            ), f"expected 2 process_restart alerts (MAX_RESTARTS+1), got {alert_count}"
        finally:
            _cleanup_session(_SID_MAXRETRY)
