"""Watchdog release rules R-007..R-010/R-016: no unsafe segmented restart."""

from unittest.mock import Mock

import pytest

from capture.watchdog import models, runner
from tests.capture_tests.watchdog.support import PARTICIPANT_ID, SESSION_ID, SITE_ID, SPONSOR_ID


@pytest.fixture
def collaborators(monkeypatch):
    args = models.WatchdogArgs(SESSION_ID, PARTICIPANT_ID, SITE_ID, SPONSOR_ID)
    mocks = {
        name: Mock()
        for name in (
            "start_forwarder",
            "wait_for_forwarder",
            "handle_clean_shutdown",
            "record_unexpected_exit",
            "mark_session_failed",
        )
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(runner, name, mock)
    mocks["wait_for_forwarder"].return_value = 0
    return args, mocks


def test_r007_clean_shutdown_does_not_increment_restart(collaborators):
    args, mocks = collaborators
    state = models.WatchdogState(clean_shutdown=True)
    assert runner.run_watchdog_loop(args, ["forwarder"], state) == 0
    assert state.restart_count == 0
    mocks["handle_clean_shutdown"].assert_called_once_with(args)
    mocks["record_unexpected_exit"].assert_not_called()


def test_r008_unexpected_exit_records_and_fails_without_restart(collaborators):
    args, mocks = collaborators
    mocks["wait_for_forwarder"].return_value = 17
    state = models.WatchdogState()
    assert runner.run_watchdog_loop(args, ["forwarder"], state) == 1
    assert state.restart_count == 1
    mocks["start_forwarder"].assert_called_once()
    recorded = mocks["record_unexpected_exit"].call_args.args
    assert recorded[:3] == (args, 17, 1)
    assert recorded[3] >= 0
    mocks["mark_session_failed"].assert_called_once_with(SESSION_ID, SPONSOR_ID)


def test_r009_failed_child_on_requested_shutdown_never_closes(collaborators):
    args, mocks = collaborators
    mocks["wait_for_forwarder"].return_value = 1
    assert runner.run_watchdog_loop(args, [], models.WatchdogState(clean_shutdown=True)) == 1
    mocks["handle_clean_shutdown"].assert_not_called()
    mocks["mark_session_failed"].assert_called_once()


def test_r010_terminal_persistence_error_is_observable(collaborators):
    args, mocks = collaborators
    mocks["mark_session_failed"].side_effect = RuntimeError("DB unavailable")
    with pytest.raises(RuntimeError, match="DB unavailable"):
        runner.run_watchdog_loop(args, [], models.WatchdogState())
    mocks["record_unexpected_exit"].assert_called_once()


def test_r016_clean_terminal_failure_is_not_success(collaborators):
    args, mocks = collaborators
    mocks["handle_clean_shutdown"].side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        runner.run_watchdog_loop(args, [], models.WatchdogState(clean_shutdown=True))
