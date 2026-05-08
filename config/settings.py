"""Consensai 1a runtime configuration.

All values load from environment variables (.env at repo root).
Required variables raise RuntimeError immediately on import if missing —
fail loud, fail early, never silently proceed with bad config.

To add a new setting:
  1. Add it here with _require() or _get(key, default)
  2. Add the key to .env and .env.example
  3. Never hardcode values anywhere else in the codebase
"""

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{key}' is not set. "
            f"Add it to your .env file and restart."
        )
    return value


def _get(key: str, default: str) -> str:
    return os.getenv(key, default)


def _get_optional(key: str) -> str | None:
    """Return the env var value, or None if unset or empty."""
    value = os.getenv(key)
    return value if value else None


def validate() -> None:
    """Check all required config values and fail with a single clear error.

    Call this at the top of every script's main() before doing any work.
    Reports all missing/invalid values at once rather than one at a time.
    """
    errors: list[str] = []

    # Required — no defaults allowed
    if not DATABASE_URL:
        errors.append("DATABASE_URL — postgres connection string")

    # Sanity-check numeric values (catches .env typos before a session starts)
    numeric_checks = {
        "SAMPLE_RATE_EEG": (SAMPLE_RATE_EEG, 1, 10000),
        "SAMPLE_RATE_HRV": (SAMPLE_RATE_HRV, 1, 10000),
        "SAMPLE_RATE_EDA": (SAMPLE_RATE_EDA, 1, 10000),
        "SAMPLE_RATE_RESPIRATION": (SAMPLE_RATE_RESPIRATION, 1, 10000),
        "EEG_CHANNEL_COUNT": (EEG_CHANNEL_COUNT, 1, 256),
        "LSL_RESOLVE_TIMEOUT": (LSL_RESOLVE_TIMEOUT, 0.1, 60.0),
        "LSL_MAX_BUFSIZE": (LSL_MAX_BUFSIZE, 1.0, 300.0),
        "WATCHDOG_TIMEOUT_EEG": (WATCHDOG_TIMEOUT_EEG, 0.1, 300.0),
        "WATCHDOG_TIMEOUT_HRV": (WATCHDOG_TIMEOUT_HRV, 0.1, 300.0),
        "WATCHDOG_TIMEOUT_EDA": (WATCHDOG_TIMEOUT_EDA, 0.1, 300.0),
        "WATCHDOG_TIMEOUT_RESPIRATION": (WATCHDOG_TIMEOUT_RESPIRATION, 0.1, 300.0),
        "CLOCK_DRIFT_RECORD_INTERVAL": (CLOCK_DRIFT_RECORD_INTERVAL, 1.0, 3600.0),
    }
    for name, (value, lo, hi) in numeric_checks.items():
        if not (lo <= value <= hi):
            errors.append(f"{name} = {value!r} (must be between {lo} and {hi})")

    try:
        uuid.UUID(DEVICE_ID)
    except ValueError:
        errors.append(f"DEVICE_ID = {DEVICE_ID!r} (must be a valid UUID)")

    if HRV_SIGNAL_SOURCE not in ("ecg", "pcg", "ppg"):
        errors.append(
            f"HRV_SIGNAL_SOURCE = {HRV_SIGNAL_SOURCE!r} (must be ecg | pcg | ppg)"
        )
    if EDA_SIGNAL_SOURCE not in ("combined", "scl", "scr"):
        errors.append(
            f"EDA_SIGNAL_SOURCE = {EDA_SIGNAL_SOURCE!r} (must be combined | scl | scr)"
        )
    if RESPIRATION_SOURCE not in ("belt_direct", "rsa_derived"):
        errors.append(
            f"RESPIRATION_SOURCE = {RESPIRATION_SOURCE!r} (must be belt_direct | rsa_derived)"
        )

    if errors:
        lines = "\n  ".join(errors)
        raise RuntimeError(
            f"Consensai config validation failed — fix these in .env before starting:\n  {lines}"
        )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Empty string default so the module can be imported without DATABASE_URL set.
# validate() enforces that it is non-empty before any production code runs.
DATABASE_URL: str = _get("DATABASE_URL", "")
TEST_DATABASE_URL: str | None = os.getenv("TEST_DATABASE_URL")

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
LOG_DIR: Path = Path(_get("LOG_DIR", "./logs"))
XDF_BACKUP_DIR: Path = Path(_get("XDF_BACKUP_DIR", "./data/xdf_backups"))

# ---------------------------------------------------------------------------
# LSL — stream names
# Must match the stream names published by your recording hardware.
# Override in .env if your device uses different names.
# ---------------------------------------------------------------------------
LSL_STREAM_EEG: str = _get("LSL_STREAM_EEG", "EEG")
LSL_STREAM_HRV: str = _get("LSL_STREAM_HRV", "HRV")
LSL_STREAM_EDA: str = _get("LSL_STREAM_EDA", "EDA")
LSL_STREAM_RESPIRATION: str = _get("LSL_STREAM_RESPIRATION", "Respiration")
LSL_STREAM_MARKER: str = _get("LSL_STREAM_MARKER", "ConsensaiMarkers")

# Seconds to wait for each stream to appear during inlet resolve at startup
LSL_RESOLVE_TIMEOUT: float = float(_get("LSL_RESOLVE_TIMEOUT", "5.0"))

# Seconds of data each inlet can buffer internally before samples are lost
LSL_MAX_BUFSIZE: float = float(_get("LSL_MAX_BUFSIZE", "10.0"))

# ---------------------------------------------------------------------------
# LSL — chunk sizes (samples pulled per pull_chunk call per modality)
# Tune relative to sample rate: smaller chunks = lower latency, more DB calls
# ---------------------------------------------------------------------------
LSL_CHUNK_EEG: int = int(_get("LSL_CHUNK_EEG", "25"))  # ~100ms at 250 Hz
LSL_CHUNK_HRV: int = int(_get("LSL_CHUNK_HRV", "1"))
LSL_CHUNK_EDA: int = int(_get("LSL_CHUNK_EDA", "4"))  # ~1s at 4 Hz
LSL_CHUNK_RESPIRATION: int = int(_get("LSL_CHUNK_RESPIRATION", "4"))

# ---------------------------------------------------------------------------
# Sample rates (Hz) — must match device configuration
# EEG:         250 Hz  (OpenBCI Cyton / research-grade headsets)
# HRV:           1 Hz  (RR-interval derived stream)
# EDA:           4 Hz  (clinical standard)
# Respiration:   4 Hz  (clinical standard)
# ---------------------------------------------------------------------------
SAMPLE_RATE_EEG: int = int(_get("SAMPLE_RATE_EEG", "250"))
SAMPLE_RATE_HRV: int = int(_get("SAMPLE_RATE_HRV", "1"))
SAMPLE_RATE_EDA: int = int(_get("SAMPLE_RATE_EDA", "4"))
SAMPLE_RATE_RESPIRATION: int = int(_get("SAMPLE_RATE_RESPIRATION", "4"))

# EEG channel count — used by lsl_forwarder for narrow-row expansion
# (one DB row per channel per sample)
EEG_CHANNEL_COUNT: int = int(_get("EEG_CHANNEL_COUNT", "8"))

# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------
DEVICE_ID: str = _get("DEVICE_ID", "00000000-0000-0000-0000-000000000001")

# ---------------------------------------------------------------------------
# Simulation
# Set to "true" in .env during development. lsl_forwarder logs this at
# startup so audit records clearly distinguish simulated from real sessions.
# ---------------------------------------------------------------------------
SIMULATION_MODE: bool = _get("SIMULATION_MODE", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Watchdog — stream health monitoring
# If no new samples arrive within WATCHDOG_TIMEOUT seconds, the forwarder
# logs an error and alerts the coordinator via the WebSocket.
# Per-modality timeouts reflect expected inter-sample gaps:
#   EEG:         3s  (4ms expected gap at 250 Hz — 3s = ~750 missed samples)
#   HRV:        10s  (1s expected gap — brief pauses are normal)
#   EDA:        10s  (250ms expected gap)
#   Respiration: 10s (250ms expected gap)
# ---------------------------------------------------------------------------
WATCHDOG_TIMEOUT_EEG: float = float(_get("WATCHDOG_TIMEOUT_EEG", "3.0"))
WATCHDOG_TIMEOUT_HRV: float = float(_get("WATCHDOG_TIMEOUT_HRV", "10.0"))
WATCHDOG_TIMEOUT_EDA: float = float(_get("WATCHDOG_TIMEOUT_EDA", "10.0"))
WATCHDOG_TIMEOUT_RESPIRATION: float = float(
    _get("WATCHDOG_TIMEOUT_RESPIRATION", "10.0")
)

# How often the watchdog check loop runs (seconds)
WATCHDOG_POLL_INTERVAL: float = float(_get("WATCHDOG_POLL_INTERVAL", "1.0"))

# ---------------------------------------------------------------------------
# Clock drift
# lsl_forwarder records remote_clock_offset at this interval (seconds).
# Non-optional — ibogaine sessions run 8+ hours; drift accumulates.
# ---------------------------------------------------------------------------
CLOCK_DRIFT_RECORD_INTERVAL: float = float(_get("CLOCK_DRIFT_RECORD_INTERVAL", "60.0"))

# ---------------------------------------------------------------------------
# Safety monitor
# ---------------------------------------------------------------------------
SAFETY_MONITOR_POLL_INTERVAL: float = float(_get("SAFETY_MONITOR_POLL_INTERVAL", "1.0"))

# ---------------------------------------------------------------------------
# SQI monitor (signal quality index)
# ---------------------------------------------------------------------------
SQI_MONITOR_POLL_INTERVAL: float = float(_get("SQI_MONITOR_POLL_INTERVAL", "5.0"))

# ---------------------------------------------------------------------------
# Recording metadata — written to session_signal_metadata at session start
# One row per modality; these are constants for the hardware/software setup.
# ---------------------------------------------------------------------------

# EEG
EEG_REFERENCE: str = _get("EEG_REFERENCE", "average")
POWER_LINE_FREQUENCY: float = float(_get("POWER_LINE_FREQUENCY", "60.0"))
CAP_MANUFACTURER: str | None = _get_optional("CAP_MANUFACTURER")
CAP_MANUFACTURER_MODEL_NAME: str | None = _get_optional("CAP_MANUFACTURER_MODEL_NAME")

# HRV — hrv_signal_source must match DB CHECK: ecg | pcg | ppg
HRV_SIGNAL_SOURCE: str = _get("HRV_SIGNAL_SOURCE", "ecg")
BEAT_DETECTION_ALGORITHM: str | None = _get_optional("BEAT_DETECTION_ALGORITHM")
BEAT_DETECTION_VERSION: str | None = _get_optional("BEAT_DETECTION_VERSION")

# EDA — eda_signal_source must match DB CHECK: combined | scl | scr
EDA_SIGNAL_SOURCE: str = _get("EDA_SIGNAL_SOURCE", "combined")
_eda_min = os.getenv("EDA_RANGE_MIN_US")
EDA_RANGE_MIN_US: float | None = float(_eda_min) if _eda_min else None
_eda_max = os.getenv("EDA_RANGE_MAX_US")
EDA_RANGE_MAX_US: float | None = float(_eda_max) if _eda_max else None

# Respiration — respiration_source must match DB CHECK: belt_direct | rsa_derived
RESPIRATION_SOURCE: str = _get("RESPIRATION_SOURCE", "belt_direct")
RESPIRATION_UNIT: str | None = _get_optional("RESPIRATION_UNIT")
