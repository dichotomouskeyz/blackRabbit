"""Compatibility wrapper for the LSL stream forwarder."""

from capture.forwarder import (
    _CLOCK_DRIFT_INSERT,
    _EDA_INSERT,
    _EEG_INSERT,
    _HRV_INSERT,
    _RESPIRATION_INSERT,
    BUFFER_MAX_CHUNKS,
    DRIFT_WARN_THRESHOLD_S,
    PAYLOAD_SCHEMA_VERSION,
    SessionConfig,
    _build_eda_rows,
    _build_eeg_rows,
    _build_hrv_rows,
    _build_respiration_rows,
    _build_stream_threads,
    _parse_args,
    _parse_uuid,
    _StreamThread,
    _verify_session_ready,
    main,
)
from config import settings

settings.validate()

__all__ = [
    "BUFFER_MAX_CHUNKS",
    "DRIFT_WARN_THRESHOLD_S",
    "PAYLOAD_SCHEMA_VERSION",
    "SessionConfig",
    "_CLOCK_DRIFT_INSERT",
    "_EDA_INSERT",
    "_EEG_INSERT",
    "_HRV_INSERT",
    "_RESPIRATION_INSERT",
    "_StreamThread",
    "_build_eda_rows",
    "_build_eeg_rows",
    "_build_hrv_rows",
    "_build_respiration_rows",
    "_build_stream_threads",
    "_parse_args",
    "_parse_uuid",
    "_verify_session_ready",
    "main",
    "settings",
]


if __name__ == "__main__":
    main()
