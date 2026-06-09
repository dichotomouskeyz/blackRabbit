"""Tests for watchdog forwarder process start/stop behavior."""

import subprocess
from unittest.mock import MagicMock

import capture.watchdog.models as models
import capture.watchdog.process as process


class TestWatchdogForwarderShutdown:
    def test_start_forwarder_uses_process_group_on_windows(self, monkeypatch):
        monkeypatch.setattr(process.os, "name", "nt", raising=False)
        monkeypatch.setattr(
            process.subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            512,
            raising=False,
        )

        popen = MagicMock()
        monkeypatch.setattr(process.subprocess, "Popen", popen)

        process.start_forwarder(["python", "-m", "capture.lsl_forwarder"])

        popen.assert_called_once_with(
            ["python", "-m", "capture.lsl_forwarder"],
            creationflags=512,
        )

    def test_stop_forwarder_sends_ctrl_break_on_windows(self, monkeypatch):
        monkeypatch.setattr(process.os, "name", "nt", raising=False)
        monkeypatch.setattr(
            process.signal,
            "CTRL_BREAK_EVENT",
            1,
            raising=False,
        )
        os_kill = MagicMock()
        monkeypatch.setattr(process.os, "kill", os_kill)

        proc = MagicMock()
        proc.pid = 123
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired(["forwarder"], 1), None]
        monkeypatch.setattr(
            process,
            "request_stop",
            MagicMock(return_value="logs/control/stop_session.signal"),
        )
        monkeypatch.setattr(process, "clear_stop_request", MagicMock())

        process.stop_forwarder(proc, "session")

        os_kill.assert_called_once_with(123, 1)
        proc.terminate.assert_not_called()
        assert proc.wait.call_count == 2

    def test_stop_forwarder_terminates_on_posix(self, monkeypatch):
        monkeypatch.setattr(process.os, "name", "posix", raising=False)
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired(["forwarder"], 1), None]
        monkeypatch.setattr(
            process,
            "request_stop",
            MagicMock(return_value="logs/control/stop_session.signal"),
        )
        monkeypatch.setattr(process, "clear_stop_request", MagicMock())

        process.stop_forwarder(proc, "session")

        proc.terminate.assert_called_once()
        assert proc.wait.call_count == 2

    def test_stop_forwarder_prefers_stop_request_file(self, monkeypatch):
        proc = MagicMock()
        proc.poll.return_value = None
        request = MagicMock(return_value="logs/control/stop_session.signal")
        clear = MagicMock()
        monkeypatch.setattr(process, "request_stop", request)
        monkeypatch.setattr(process, "clear_stop_request", clear)

        process.stop_forwarder(proc, "session")

        request.assert_called_once_with("session")
        clear.assert_called_once_with("session")
        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()

    def test_wait_for_forwarder_polls_without_blocking_wait(self, monkeypatch):
        proc = MagicMock()
        proc.poll.side_effect = [None, None, 0]
        proc.returncode = 0
        sleep = MagicMock()
        monkeypatch.setattr(process.time, "sleep", sleep)

        assert process.wait_for_forwarder(proc) == 0

        proc.wait.assert_not_called()
        assert sleep.call_count == 2
        sleep.assert_called_with(models.PROCESS_POLL_INTERVAL_S)
