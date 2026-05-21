"""Shared forwarder models and constants."""

import uuid
from dataclasses import dataclass

PAYLOAD_SCHEMA_VERSION = "1.0"
BUFFER_MAX_CHUNKS = 200
DRIFT_WARN_THRESHOLD_S = 0.100
LOG_EVERY_N_CHUNKS = 50


def _validate_uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError(f"{field} is not a valid UUID: {value!r}")


@dataclass(frozen=True)
class SessionConfig:
    session_id: str
    participant_id: str
    site_id: str
    sponsor_id: str
    eeg_channel_names: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        for field in ("session_id", "participant_id", "site_id", "sponsor_id"):
            _validate_uuid(getattr(self, field), f"SessionConfig.{field}")
