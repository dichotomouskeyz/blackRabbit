"""Watchdog package and compatibility exports."""

import os
import signal
import subprocess  # nosec B404
import time

from capture.control import clear_stop_request, request_stop
from capture.watchdog import db as _db
from capture.watchdog import models as _models
from capture.watchdog import process as _process
from capture.watchdog import runner as _runner
from capture.watchdog.cli import (
    build_forwarder_cmd as _build_forwarder_cmd,
)
from capture.watchdog.cli import (
    parse_args as _parse_args,
)
from capture.watchdog.cli import (
    parse_uuid as _parse_uuid,
)
from capture.watchdog.cli import (
    watchdog_args as _watchdog_args,
)
from capture.watchdog.db import lookup_compound as _lookup_compound
from capture.watchdog.models import WatchdogArgs, WatchdogState
from capture.watchdog.runner import (
    handle_clean_shutdown as _handle_clean_shutdown,
)
from capture.watchdog.runner import (
    install_signal_handlers as _install_signal_handlers,
)
from config import settings

_run_watchdog_loop_impl = _runner.run_watchdog_loop
_record_unexpected_exit_impl = _runner.record_unexpected_exit
_restart_delay_s_impl = _runner.restart_delay_s
_runner_main_impl = _runner.main

WATCHDOG_ALGORITHM_NAME = _models.WATCHDOG_ALGORITHM_NAME
WATCHDOG_ALGORITHM_VERSION = _models.WATCHDOG_ALGORITHM_VERSION
MAX_RESTARTS = _models.MAX_RESTARTS
RESTART_DELAY_BASE_S = _models.RESTART_DELAY_BASE_S
RESTART_DELAY_MAX_S = _models.RESTART_DELAY_MAX_S
GRACEFUL_SHUTDOWN_TIMEOUT_S = _models.GRACEFUL_SHUTDOWN_TIMEOUT_S
PROCESS_POLL_INTERVAL_S = _models.PROCESS_POLL_INTERVAL_S


def _sync_compat_patches() -> None:
    _models.MAX_RESTARTS = MAX_RESTARTS
    _models.RESTART_DELAY_BASE_S = RESTART_DELAY_BASE_S
    _models.RESTART_DELAY_MAX_S = RESTART_DELAY_MAX_S
    _models.GRACEFUL_SHUTDOWN_TIMEOUT_S = GRACEFUL_SHUTDOWN_TIMEOUT_S
    _models.PROCESS_POLL_INTERVAL_S = PROCESS_POLL_INTERVAL_S
    _process.request_stop = request_stop
    _process.clear_stop_request = clear_stop_request


def _log_restart(*args, **kwargs):
    _sync_compat_patches()
    return _db.log_restart(*args, **kwargs)


def _mark_session_closing(session_id: str) -> None:
    return _db.mark_session_closing(session_id)


def _mark_session_failed(session_id: str) -> None:
    return _db.mark_session_failed(session_id)


def _start_forwarder(forwarder_cmd: list[str]):
    _sync_compat_patches()
    return _process.start_forwarder(forwarder_cmd)


def _stop_forwarder(process, session_id: str) -> None:
    _sync_compat_patches()
    return _process.stop_forwarder(process, session_id)


def _wait_for_forwarder(process) -> int:
    _sync_compat_patches()
    return _process.wait_for_forwarder(process)


def _record_unexpected_exit(*args, **kwargs) -> None:
    _sync_compat_patches()
    _runner.log_restart = _log_restart
    return _record_unexpected_exit_impl(*args, **kwargs)


def _restart_delay_s(restart_count: int) -> float:
    _sync_compat_patches()
    return _restart_delay_s_impl(restart_count)


def _run_watchdog_loop(args: WatchdogArgs, forwarder_cmd: list[str], state: WatchdogState) -> None:
    _sync_compat_patches()
    _runner.start_forwarder = _start_forwarder
    _runner.wait_for_forwarder = _wait_for_forwarder
    _runner.record_unexpected_exit = _record_unexpected_exit_impl
    _runner.restart_delay_s = _restart_delay_s_impl
    _runner.mark_session_failed = _mark_session_failed
    return _run_watchdog_loop_impl(args, forwarder_cmd, state)


def main() -> None:
    _sync_compat_patches()
    _runner.run_watchdog_loop = _run_watchdog_loop
    _runner.build_forwarder_cmd = _build_forwarder_cmd
    _runner.watchdog_args = _watchdog_args
    _runner.parse_args = _parse_args
    return _runner_main_impl()


__all__ = [
    "GRACEFUL_SHUTDOWN_TIMEOUT_S",
    "MAX_RESTARTS",
    "PROCESS_POLL_INTERVAL_S",
    "RESTART_DELAY_BASE_S",
    "RESTART_DELAY_MAX_S",
    "WATCHDOG_ALGORITHM_NAME",
    "WATCHDOG_ALGORITHM_VERSION",
    "WatchdogArgs",
    "WatchdogState",
    "_build_forwarder_cmd",
    "_handle_clean_shutdown",
    "_install_signal_handlers",
    "_log_restart",
    "_lookup_compound",
    "_mark_session_closing",
    "_mark_session_failed",
    "_parse_args",
    "_parse_uuid",
    "_record_unexpected_exit",
    "_restart_delay_s",
    "_run_watchdog_loop",
    "_start_forwarder",
    "_stop_forwarder",
    "_wait_for_forwarder",
    "_watchdog_args",
    "clear_stop_request",
    "main",
    "os",
    "request_stop",
    "settings",
    "signal",
    "subprocess",
    "time",
]
