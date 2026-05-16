"""Tests for capture.watchdog — audit trail and end-to-end crash chain."""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env"))

import capture.watchdog as watchdog_module  # noqa: E402

from tests.capture_tests.watchdog.support import (  # noqa: E402
    _PART_UUID,
    _SITE_UUID,
    _SPONSOR_UUID,
    _cleanup_session,
    _direct_conn,
    _insert_session,
)

_SID_ALERT = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a01"
_SID_AUDIT = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a02"
_SID_E2E = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a03"


@pytest.mark.integration
class TestWatchdogAuditTrail:
    def test_log_restart_writes_alert_event(self, monkeypatch):
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
            mock_proc.poll.return_value = 1
            mock_proc.returncode = 1

            monkeypatch.setattr(
                sys,
                "argv",
                [
                    "watchdog",
                    "--session-id", _SID_E2E,
                    "--participant-id", "aaaa0003-0000-0000-0000-000000000003",
                    "--site-id", "bbbb0000-0000-0000-0000-000000000001",
                    "--sponsor-id", "cccc0000-0000-0000-0000-000000000001",
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
