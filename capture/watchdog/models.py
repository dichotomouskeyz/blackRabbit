"""Shared watchdog models and restart policy."""

import subprocess  # nosec B404
from dataclasses import dataclass

WATCHDOG_ALGORITHM_NAME = "watchdog"
WATCHDOG_ALGORITHM_VERSION = "1.0.0"

# Segmented resume is not supported by the local MVP. Never reset indices.
MAX_RESTARTS = 0
RESTART_DELAY_BASE_S = 5.0
RESTART_DELAY_MAX_S = 60.0
GRACEFUL_SHUTDOWN_TIMEOUT_S = 30.0
PROCESS_POLL_INTERVAL_S = 0.25


@dataclass(frozen=True)
class WatchdogArgs:
    session_id: str
    participant_id: str
    site_id: str
    sponsor_id: str


@dataclass
class WatchdogState:
    process: subprocess.Popen | None = None
    restart_count: int = 0
    clean_shutdown: bool = False
