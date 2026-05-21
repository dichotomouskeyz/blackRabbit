"""Tests for watchdog session state transitions."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env"))

import capture.watchdog.db as watchdog_db  # noqa: E402
import capture.watchdog.models as watchdog_models  # noqa: E402
import capture.watchdog.process as watchdog_process  # noqa: E402
import capture.watchdog.runner as watchdog_runner  # noqa: E402
from config import settings  # noqa: E402
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
_SID_WRONG_SPONSOR = "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a09"
_OTHER_SPONSOR = "f1d00009-0000-4444-dddd-000000000099"


@pytest.mark.integration
class TestWatchdogSessionTransitions:
    def test_mark_session_closing_sets_status(self, monkeypatch):
        monkeypatch.setattr(
            settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_CLOSING, status="active")
        try:
            watchdog_db.mark_session_closing(_SID_CLOSING, _SPONSOR_UUID)

            assert _get_status(_SID_CLOSING) == "closing"
            audit_types = _get_audit_types(_SID_CLOSING)
            assert "session_status_transition" in audit_types
            assert "watermark_verified" not in audit_types
            assert "watermark_failed" not in audit_types
        finally:
            _cleanup_session(_SID_CLOSING)

    def test_mark_session_closing_is_noop_if_already_closing(self, monkeypatch):
        monkeypatch.setattr(
            settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_NOOP_CLOSING, status="closing")
        try:
            watchdog_db.mark_session_closing(_SID_NOOP_CLOSING, _SPONSOR_UUID)

            assert _get_status(_SID_NOOP_CLOSING) == "closing"
        finally:
            _cleanup_session(_SID_NOOP_CLOSING)

    def test_mark_session_failed_sets_status_and_fires_trigger(self, monkeypatch):
        monkeypatch.setattr(
            settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_FAILED, status="active")
        try:
            watchdog_db.mark_session_failed(_SID_FAILED, _SPONSOR_UUID)

            assert _get_status(_SID_FAILED) == "failed"
            audit_types = _get_audit_types(_SID_FAILED)
            assert "session_status_transition" in audit_types
            assert "watermark_failed" in audit_types
        finally:
            _cleanup_session(_SID_FAILED)

    def test_mark_session_failed_is_noop_on_closed_session(self, monkeypatch):
        monkeypatch.setattr(
            settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_NOOP_CLOSED, status="closed")
        try:
            watchdog_db.mark_session_failed(_SID_NOOP_CLOSED, _SPONSOR_UUID)

            assert _get_status(_SID_NOOP_CLOSED) == "closed"
        finally:
            _cleanup_session(_SID_NOOP_CLOSED)

    def test_mark_session_closing_wrong_sponsor_is_noop(self, monkeypatch):
        monkeypatch.setattr(
            settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_WRONG_SPONSOR, status="active")
        try:
            watchdog_db.mark_session_closing(_SID_WRONG_SPONSOR, _OTHER_SPONSOR)

            assert _get_status(_SID_WRONG_SPONSOR) == "active"
        finally:
            _cleanup_session(_SID_WRONG_SPONSOR)

    def test_mark_session_failed_wrong_sponsor_is_noop(self, monkeypatch):
        monkeypatch.setattr(
            settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        _insert_session(_SID_WRONG_SPONSOR, status="active")
        try:
            watchdog_db.mark_session_failed(_SID_WRONG_SPONSOR, _OTHER_SPONSOR)

            assert _get_status(_SID_WRONG_SPONSOR) == "active"
        finally:
            _cleanup_session(_SID_WRONG_SPONSOR)

    def test_max_restarts_marks_session_failed_end_to_end(self, monkeypatch):
        monkeypatch.setattr(
            settings, "DATABASE_URL", os.getenv("TEST_DATABASE_URL")
        )
        monkeypatch.setattr(watchdog_models, "MAX_RESTARTS", 1)
        monkeypatch.setattr(watchdog_models, "RESTART_DELAY_BASE_S", 0.0)

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
            with patch.object(watchdog_process.subprocess, "Popen", return_value=mock_proc):
                with patch.object(watchdog_runner.time, "sleep"):
                    watchdog_runner.main()

            assert _get_status(_SID_MAXRETRY) == "failed", (
                "session should be 'failed' after max restarts exhausted"
            )
            audit_types = _get_audit_types(_SID_MAXRETRY)
            assert "session_status_transition" in audit_types
            assert "watermark_failed" in audit_types, (
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
