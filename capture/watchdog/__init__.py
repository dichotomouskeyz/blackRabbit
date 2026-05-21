"""Watchdog package exports."""

from capture.control import clear_stop_request, request_stop
from capture.watchdog.models import (
    GRACEFUL_SHUTDOWN_TIMEOUT_S,
    MAX_RESTARTS,
    PROCESS_POLL_INTERVAL_S,
    RESTART_DELAY_BASE_S,
    RESTART_DELAY_MAX_S,
    WATCHDOG_ALGORITHM_NAME,
    WATCHDOG_ALGORITHM_VERSION,
    WatchdogArgs,
    WatchdogState,
)
from capture.watchdog.runner import main

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
    "clear_stop_request",
    "main",
    "request_stop",
]
