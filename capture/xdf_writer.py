"""XDF backup writer for Consensai 1a.

Writes a valid XDF (Extensible Data Format) file in parallel with TimescaleDB.
One file per session, stored in XDF_BACKUP_DIR. The file is the authoritative
reconciliation source if DB writes fail.

All four modality threads call write_samples() concurrently; an internal lock
serializes disk writes. The file is finalized (footers written, handle closed)
by calling close() once, after all threads have stopped.

XDF format reference: https://github.com/sccn/xdf/wiki/Specifications v1.0
"""

import struct
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from capture.logger import get_logger
from config import settings

log = get_logger("xdf_writer")

# ---------------------------------------------------------------------------
# XDF constants
# ---------------------------------------------------------------------------
_XDF_MAGIC = b"XDF:"

_TAG_FILE_HEADER = 1
_TAG_STREAM_HEADER = 2
_TAG_SAMPLES = 3
_TAG_STREAM_FOOTER = 6

# Fixed stream IDs for this session (1-indexed, must match stream headers)
_STREAM_IDS: dict[str, int] = {
    "EEG": 1,
    "HRV": 2,
    "EDA": 3,
    "Respiration": 4,
}

_CHANNEL_COUNTS: dict[str, int] = {
    "EEG": settings.EEG_CHANNEL_COUNT,
    "HRV": 1,
    "EDA": 1,
    "Respiration": 1,
}

_SAMPLE_RATES: dict[str, float] = {
    "EEG": float(settings.SAMPLE_RATE_EEG),
    "HRV": float(settings.SAMPLE_RATE_HRV),
    "EDA": float(settings.SAMPLE_RATE_EDA),
    "Respiration": float(settings.SAMPLE_RATE_RESPIRATION),
}


# ---------------------------------------------------------------------------
# Binary helpers
# ---------------------------------------------------------------------------


def _encode_varlen(n: int) -> bytes:
    """XDF variable-length integer: 1-byte prefix gives number of data bytes."""
    if n <= 0xFF:
        return b"\x01" + struct.pack("<B", n)
    elif n <= 0xFFFF:
        return b"\x02" + struct.pack("<H", n)
    elif n <= 0xFFFFFFFF:
        return b"\x04" + struct.pack("<I", n)
    else:
        return b"\x08" + struct.pack("<Q", n)


def _write_chunk(f: IO[bytes], tag: int, payload: bytes) -> None:
    """Serialize one XDF chunk to an open binary file handle."""
    tag_bytes = struct.pack("<H", tag)
    full = tag_bytes + payload
    f.write(_encode_varlen(len(full)))
    f.write(full)


def _stream_header_xml(
    stream_name: str, session_id: str, site_id: str, sponsor_id: str
) -> str:
    n_ch = _CHANNEL_COUNTS[stream_name]
    rate = _SAMPLE_RATES[stream_name]
    return (
        '<?xml version="1.0"?><info>'
        f"<name>{stream_name}</name>"
        f"<type>{stream_name}</type>"
        f"<channel_count>{n_ch}</channel_count>"
        f"<nominal_srate>{rate}</nominal_srate>"
        "<channel_format>float32</channel_format>"
        f"<source_id>consensai-{stream_name.lower()}</source_id>"
        f"<session_id>{session_id}</session_id>"
        f"<site_id>{site_id}</site_id>"
        f"<sponsor_id>{sponsor_id}</sponsor_id>"
        f"<created_at>{datetime.now(timezone.utc).isoformat()}</created_at>"
        "</info>"
    )


# ---------------------------------------------------------------------------
# XDFWriter
# ---------------------------------------------------------------------------


class XDFWriter:
    """Thread-safe XDF file writer. One instance per session.

    All modality threads call write_samples() concurrently as chunks arrive.
    An internal lock serializes disk I/O. Call close() once after all threads
    stop to write stream footers and flush the file.

    If the file cannot be opened, __init__ raises OSError. If a subsequent
    write fails, the error is logged and the chunk is silently dropped — the
    DB write path is not affected.
    """

    def __init__(self, session_id: str, site_id: str, sponsor_id: str) -> None:
        self._session_id = session_id
        self._lock = threading.Lock()
        self._closed = False

        # Per-stream statistics (protected by _lock)
        self._sample_counts: dict[str, int] = {k: 0 for k in _STREAM_IDS}
        self._first_ts: dict[str, float | None] = {k: None for k in _STREAM_IDS}
        self._last_ts: dict[str, float | None] = {k: None for k in _STREAM_IDS}

        # Create output directory and open file
        xdf_dir = Path(settings.XDF_BACKUP_DIR)
        xdf_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._path = xdf_dir / f"session_{session_id}_{ts_str}.xdf"
        self._f: IO[bytes] = open(self._path, "wb")

        # Write file header + stream headers
        self._f.write(_XDF_MAGIC)
        _write_chunk(
            self._f,
            _TAG_FILE_HEADER,
            b'<?xml version="1.0"?><info><version>1.0</version></info>',
        )
        for stream_name, stream_id in _STREAM_IDS.items():
            xml = _stream_header_xml(stream_name, session_id, site_id, sponsor_id)
            _write_chunk(
                self._f,
                _TAG_STREAM_HEADER,
                struct.pack("<I", stream_id) + xml.encode("utf-8"),
            )
        self._f.flush()

        log.info(
            "XDF file opened",
            extra={"xdf_path": str(self._path), "session_id": session_id},
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def write_samples(
        self,
        stream_name: str,
        samples: list[list[float]],
        timestamps: list[float],
    ) -> None:
        """Write one chunk of samples for a single stream.

        samples:    list of per-sample channel vectors, e.g. [[ch0, ch1, ...], ...]
        timestamps: list of LSL timestamps (float64), one per sample

        Silently no-ops if already closed or if no samples are provided.
        Logs and continues on I/O error — never raises to the caller.
        """
        if not samples or self._closed:
            return

        stream_id = _STREAM_IDS[stream_name]
        n_samples = len(timestamps)
        collection = time.time()

        # Build payload: stream_id + collection_time + num_samples +
        # per-sample (timestamp + float32 channel values)
        buf = bytearray()
        buf += struct.pack("<I", stream_id)
        buf += struct.pack("<d", collection)
        buf += _encode_varlen(n_samples)
        for ts, sample in zip(timestamps, samples):
            buf += struct.pack("<d", ts)
            for val in sample:
                buf += struct.pack("<f", float(val))

        with self._lock:
            if self._closed:
                return
            try:
                _write_chunk(self._f, _TAG_SAMPLES, bytes(buf))
                self._f.flush()
            except OSError as exc:
                log.error(
                    "XDF write failed — chunk dropped",
                    extra={"stream_name": stream_name, "error": str(exc)},
                )
                return

            # Update statistics
            self._sample_counts[stream_name] += n_samples
            if self._first_ts[stream_name] is None:
                self._first_ts[stream_name] = timestamps[0]
            self._last_ts[stream_name] = timestamps[-1]

    def close(self) -> None:
        """Write stream footers, flush, and close the file.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True

            for stream_name, stream_id in _STREAM_IDS.items():
                n = self._sample_counts[stream_name]
                first = self._first_ts[stream_name] or 0.0
                last = self._last_ts[stream_name] or 0.0
                footer_xml = (
                    '<?xml version="1.0"?><info>'
                    f"<first_timestamp>{first}</first_timestamp>"
                    f"<last_timestamp>{last}</last_timestamp>"
                    f"<sample_count>{n}</sample_count>"
                    "</info>"
                ).encode("utf-8")
                _write_chunk(
                    self._f,
                    _TAG_STREAM_FOOTER,
                    struct.pack("<I", stream_id) + footer_xml,
                )

            self._f.flush()
            self._f.close()

        log.info(
            "XDF file closed",
            extra={
                "xdf_path": str(self._path),
                "session_id": self._session_id,
                "sample_counts": self._sample_counts,
            },
        )

    # ------------------------------------------------------------------
    # Read-only properties (for tests)
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def sample_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._sample_counts)
