"""Shared reconciliation constants and result models."""

from dataclasses import dataclass, field
from pathlib import Path

_XDF_MAGIC = b"XDF:"
_TAG_STREAM_HEADER = 2
_TAG_SAMPLES = 3
_TAG_STREAM_FOOTER = 6

_STREAM_TABLES: dict[str, str] = {
    "EEG": "eeg_samples",
    "HRV": "hrv_samples",
    "EDA": "eda_samples",
    "Respiration": "respiration_samples",
}
_ECHO_STREAM_NAME = "ECHO"

BACKFILL_CHUNK_SIZE_ROWS: int = 1_000
_BACKFILL_LOG_EVERY_N_COMMITS: int = 10


class XDFReadError(Exception):
    """XDF file is missing, has invalid magic, or cannot be parsed."""


class XDFTruncatedError(XDFReadError):
    """XDF file has no stream footers, usually because capture was killed."""


@dataclass
class StreamResult:
    xdf_count: int
    db_count: int
    gap: int


@dataclass
class ReconciliationReport:
    session_id: str
    xdf_path: Path
    streams: dict[str, StreamResult] = field(default_factory=dict)
    is_reconciled: bool = False
    ran_at: str = ""
    max_clock_drift_s: float | None = None

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "xdf_path": str(self.xdf_path),
            "is_reconciled": self.is_reconciled,
            "ran_at": self.ran_at,
            "max_clock_drift_s": self.max_clock_drift_s,
            "streams": {
                name: {
                    "xdf_count": result.xdf_count,
                    "db_count": result.db_count,
                    "gap": result.gap,
                }
                for name, result in self.streams.items()
            },
        }


@dataclass(frozen=True)
class SessionMeta:
    participant_id: str
    site_id: str
    sponsor_id: str
