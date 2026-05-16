"""Tests for watchdog session state transitions."""

import os
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
    _get_audit_types,
    _get_status,
    _insert_session,
)

_SID_CLOSING = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a04"
_SID_FAILED = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a05"
_SID_MAXRETRY = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a06"
_SID_NOOP_CLOSING = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a07"
_SID_NOOP_CLOSED = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a08"


@pytest.mark.integration
class TestWatchdogSessionTransitions:
    def test_mark_session_closing_sets_status(self, monkeypatch):
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
        monkeypatch.setattr(
            watchdog_module.settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        monkeypatch.setattr(watchdog_module, "MAX_RESTARTS", 1)
        monkeypatch.setattr(watchdog_module, "RESTART_DELAY_BASE_S", 0.0)

        _insert_session(_SID_MAXRETRY, status="active")

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_proc.returncode = 1

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "watchdog",
                "--session-id", _SID_MAXRETRY,
                "--participant-id", _PART_UUID,
                "--site-id", _SITE_UUID,
                "--sponsor-id", _SPONSOR_UUID,
            ],
        )

        try:
            with patch("capture.watchdog.subprocess.Popen", return_value=mock_proc):
                with patch("capture.watchdog.time.sleep"):
                    watchdog_module.main()

            assert _get_status(_SID_MAXRETRY) == "failed", (
                "session should be 'failed' after max restarts exhausted"
            )
            assert "watermark_failed" in _get_audit_types(_SID_MAXRETRY), (
                "watermark_failed must be written to audit_events"
            )

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

            assert alert_count == 2, (
                f"expected 2 process_restart alerts (MAX_RESTARTS+1), got {alert_count}"
            )
        finally:
            _cleanup_session(_SID_MAXRETRY)
