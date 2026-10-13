"""untitledplatform_1a runtime configuration.

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


def _get_optional_csv(key: str) -> tuple[str, ...] | None:
    value = _get_optional(key)
    if value is None:
        return None
    items = tuple(part.strip() for part in value.split(",") if part.strip())
    return items or None


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
        "SIMULATED_ECHO_MARKER_INTERVAL": (
            SIMULATED_ECHO_MARKER_INTERVAL,
            0.5,
            3600.0,
        ),
    }
    for name, (value, lo, hi) in numeric_checks.items():
        if not (lo <= value <= hi):
            errors.append(f"{name} = {value!r} (must be between {lo} and {hi})")

    try:
        uuid.UUID(DEVICE_ID)
    except ValueError:
        errors.append(f"DEVICE_ID = {DEVICE_ID!r} (must be a valid UUID)")

    if HRV_SIGNAL_SOURCE not in ("ecg", "pcg", "ppg"):
        errors.append(f"HRV_SIGNAL_SOURCE = {HRV_SIGNAL_SOURCE!r} (must be ecg | pcg | ppg)")
    if EDA_SIGNAL_SOURCE not in ("combined", "scl", "scr"):
        errors.append(f"EDA_SIGNAL_SOURCE = {EDA_SIGNAL_SOURCE!r} (must be combined | scl | scr)")
    if EEG_SENSOR_FORM not in ("cap", "individual_electrodes", "dry_headset", "other", "unknown"):
        errors.append(
            "EEG_SENSOR_FORM = "
            f"{EEG_SENSOR_FORM!r} "
            "(must be cap | individual_electrodes | dry_headset | other | unknown)"
        )
    if EEG_ELECTRODE_SYSTEM not in ("ten_twenty", "ten_ten", "custom", "unknown"):
        errors.append(
            f"EEG_ELECTRODE_SYSTEM = {EEG_ELECTRODE_SYSTEM!r} "
            "(must be ten_twenty | ten_ten | custom | unknown)"
        )
    if EEG_ELECTRODE_TYPE not in ("wet", "dry", "sponge", "other", "unknown"):
        errors.append(
            f"EEG_ELECTRODE_TYPE = {EEG_ELECTRODE_TYPE!r} "
            "(must be wet | dry | sponge | other | unknown)"
        )
    if HRV_ELECTRODE_PLACEMENT not in (
        "chest",
        "limb_leads",
        "wrist",
        "finger",
        "ear",
        "other",
        "not_applicable",
        "unknown",
    ):
        errors.append(
            f"HRV_ELECTRODE_PLACEMENT = {HRV_ELECTRODE_PLACEMENT!r} "
            "(must be chest | limb_leads | wrist | finger | ear | other | not_applicable | unknown)"
        )
    if HRV_ELECTRODE_TYPE not in (
        "ag_agcl",
        "dry",
        "textile",
        "optical",
        "piezo",
        "other",
        "not_applicable",
        "unknown",
    ):
        errors.append(
            f"HRV_ELECTRODE_TYPE = {HRV_ELECTRODE_TYPE!r} "
            "(must be ag_agcl | dry | textile | optical | piezo | other | not_applicable | unknown)"
        )
    if RESPIRATION_SOURCE not in ("belt_direct", "rsa_derived"):
        errors.append(
            f"RESPIRATION_SOURCE = {RESPIRATION_SOURCE!r} (must be belt_direct | rsa_derived)"
        )
    if CAPTURE_SOURCE not in ("simulated", "hardware"):
        errors.append(f"CAPTURE_SOURCE = {CAPTURE_SOURCE!r} (must be simulated | hardware)")
    if EEG_CHANNEL_NAMES is not None and len(EEG_CHANNEL_NAMES) != EEG_CHANNEL_COUNT:
        errors.append(
            "EEG_CHANNEL_NAMES length must match EEG_CHANNEL_COUNT "
            f"({len(EEG_CHANNEL_NAMES)} != {EEG_CHANNEL_COUNT})"
        )

    if errors:
        lines = "\n  ".join(errors)
        raise RuntimeError(
            "untitledplatform_1a config validation failed — fix these in .env before starting:"
            f"\n  {lines}"
        )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Empty string default so the module can be imported without DATABASE_URL set.
# validate() enforces that it is non-empty before any production code runs.
DATABASE_URL: str = _get("DATABASE_URL", "")
TEST_DATABASE_URL: str | None = os.getenv("TEST_DATABASE_URL")

# ---------------------------------------------------------------------------
# Operator UI / API (Phase 4b) — all OPTIONAL (INV-015).
# These must never be required by validate(): the capture/ARC paths import and
# validate unchanged for operators who do not run the UI. NEXT_PUBLIC_* is a
# JS build-time client var and lives only in the JS env, never here.
# ---------------------------------------------------------------------------
# Read-only Postgres role connection string for the API direct-SQL path
# (INV-002 — GRANT SELECT-only). Optional at import/validate (INV-015), but the
# API read path REQUIRES it: api.deps._readonly_url() raises RuntimeError when it
# is unset. There is NO TEST_DATABASE_URL (or other) fallback — that would risk a
# write-capable connection on the read path, so it fails loud instead.
API_READONLY_DATABASE_URL: str | None = _get_optional("API_READONLY_DATABASE_URL")

# AI SDK agent route key; absence disables the agent route only (EA-004).
ANTHROPIC_API_KEY: str | None = _get_optional("ANTHROPIC_API_KEY")

# Base URL the UI uses to reach the API (informational, Python side).
API_BASE_URL: str | None = _get_optional("API_BASE_URL")

# Server-injected tenant context for the API (INV-001 / EA-003: one
# sponsor/site per local deployment). Optional — tests override the dependency.
API_SPONSOR_ID: str | None = _get_optional("API_SPONSOR_ID")
API_SITE_ID: str | None = _get_optional("API_SITE_ID")

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
LSL_STREAM_MARKER: str = _get("LSL_STREAM_MARKER", "ECHOMarkers")

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
# EDA:           4 Hz  (common research default)
# Respiration:   4 Hz  (common research default)
# ---------------------------------------------------------------------------
SAMPLE_RATE_EEG: int = int(_get("SAMPLE_RATE_EEG", "250"))
SAMPLE_RATE_HRV: int = int(_get("SAMPLE_RATE_HRV", "1"))
SAMPLE_RATE_EDA: int = int(_get("SAMPLE_RATE_EDA", "4"))
SAMPLE_RATE_RESPIRATION: int = int(_get("SAMPLE_RATE_RESPIRATION", "4"))

# EEG channel count — used by lsl_forwarder for narrow-row expansion
# (one DB row per channel per sample)
EEG_CHANNEL_COUNT: int = int(_get("EEG_CHANNEL_COUNT", "8"))
EEG_CHANNEL_NAMES: tuple[str, ...] | None = _get_optional_csv("EEG_CHANNEL_NAMES")

# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------
DEVICE_ID: str = _get("DEVICE_ID", "00000000-0000-0000-0000-000000000001")
APP_VERSION: str = _get("APP_VERSION", "unknown")
PAYLOAD_SCHEMA_VERSION: str = _get("PAYLOAD_SCHEMA_VERSION", "1.0")

# ---------------------------------------------------------------------------
# Capture source
# CAPTURE_SOURCE is the persisted source of truth for simulated vs hardware runs.
# SIMULATION_MODE remains a runtime convenience alias.
# Default stays simulated if neither env var is set.
# ---------------------------------------------------------------------------
_simulation_mode_env = _get("SIMULATION_MODE", "true").lower() == "true"
CAPTURE_SOURCE: str = _get("CAPTURE_SOURCE", "simulated" if _simulation_mode_env else "hardware")
SIMULATION_MODE: bool = CAPTURE_SOURCE == "simulated"
SIMULATED_ECHO_MARKER_INTERVAL: float = float(_get("SIMULATED_ECHO_MARKER_INTERVAL", "5.0"))

# Modalities that must have session_signal_metadata rows before capture starts.
# Comma-separated env override (e.g. for a future eye-tracking modality).
REQUIRED_MODALITIES: frozenset[str] = frozenset(
    m.strip()
    for m in _get("REQUIRED_MODALITIES", "eeg,hrv,eda,respiration").split(",")
    if m.strip()
)

# ---------------------------------------------------------------------------
# Watchdog — stream health monitoring
# If no new samples arrive within WATCHDOG_TIMEOUT seconds, the forwarder
# logs an error and records a local alert for post-session review.
# Per-modality timeouts reflect expected inter-sample gaps:
#   EEG:         3s  (4ms expected gap at 250 Hz — 3s = ~750 missed samples)
#   HRV:        10s  (1s expected gap — brief pauses are normal)
#   EDA:        10s  (250ms expected gap)
#   Respiration: 10s (250ms expected gap)
# ---------------------------------------------------------------------------
WATCHDOG_TIMEOUT_EEG: float = float(_get("WATCHDOG_TIMEOUT_EEG", "3.0"))
WATCHDOG_TIMEOUT_HRV: float = float(_get("WATCHDOG_TIMEOUT_HRV", "10.0"))
WATCHDOG_TIMEOUT_EDA: float = float(_get("WATCHDOG_TIMEOUT_EDA", "10.0"))
WATCHDOG_TIMEOUT_RESPIRATION: float = float(_get("WATCHDOG_TIMEOUT_RESPIRATION", "10.0"))

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
EEG_SENSOR_FORM: str = _get("EEG_SENSOR_FORM", "cap")
EEG_ELECTRODE_SYSTEM: str = _get("EEG_ELECTRODE_SYSTEM", "ten_twenty")
EEG_ELECTRODE_TYPE: str = _get("EEG_ELECTRODE_TYPE", "unknown")
POWER_LINE_FREQUENCY: float = float(_get("POWER_LINE_FREQUENCY", "60.0"))
CAP_MANUFACTURER: str | None = _get_optional("CAP_MANUFACTURER")
CAP_MANUFACTURER_MODEL_NAME: str | None = _get_optional("CAP_MANUFACTURER_MODEL_NAME")

# HRV — hrv_signal_source must match DB CHECK: ecg | pcg | ppg
HRV_SIGNAL_SOURCE: str = _get("HRV_SIGNAL_SOURCE", "ecg")
HRV_ELECTRODE_PLACEMENT: str = _get("HRV_ELECTRODE_PLACEMENT", "unknown")
HRV_ELECTRODE_TYPE: str = _get("HRV_ELECTRODE_TYPE", "unknown")
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
