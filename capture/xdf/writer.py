"""XDF backup writer for untitledplatform_1a.

Writes a valid XDF (Extensible Data Format) file in parallel with TimescaleDB.
One file per session, stored in XDF_BACKUP_DIR. The file is the authoritative
local reconciliation source for capture continuity — if DB writes fail, this
XDF is the ground truth used to backfill missing data.

All four modality threads call write_samples() concurrently; an internal lock
serializes disk writes. The file is finalized (footers written, handle closed)
by calling close() once, after all threads have stopped.

XDF format reference: https://github.com/sccn/xdf/wiki/Specifications v1.0
"""

import struct
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from capture.logger import get_logger
from config import settings

from .binary import write_chunk
from .constants import (
    BIOSIGNAL_STREAM_IDS,
    STREAM_IDS,
    TAG_FILE_HEADER,
    TAG_SAMPLES,
    TAG_STREAM_FOOTER,
    TAG_STREAM_HEADER,
    XDF_MAGIC,
)
from .metadata import _stream_footer_xml, _stream_header_xml
from .samples import _build_biosignal_payload, _build_marker_payload

log = get_logger("xdf_writer")


class XDFWriter:
    """Thread-safe XDF file writer. One instance per session.

    All modality threads call write_samples() concurrently as chunks arrive.
    An internal lock serializes disk I/O. Call close() once after all threads
    stop to write stream footers and flush the file.

    If the file cannot be opened, __init__ raises OSError. If a subsequent
    write fails, the error is logged and the chunk is silently dropped — the
    DB write path is not affected.
    """

    def __init__(
        self,
        session_id: str,
        participant_id: str,
        site_id: str,
        sponsor_id: str,
    ) -> None:
        self._session_id = session_id
        self._lock = threading.Lock()
        self._closed = False

        # Per-stream statistics (protected by _lock)
        self._sample_counts: dict[str, int] = {k: 0 for k in STREAM_IDS}
        self._first_ts: dict[str, float | None] = {k: None for k in STREAM_IDS}
        self._last_ts: dict[str, float | None] = {k: None for k in STREAM_IDS}

        # Create output directory and open file
        xdf_dir = Path(settings.XDF_BACKUP_DIR)
        xdf_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._path = xdf_dir / f"session_{session_id}_{ts_str}.xdf"
        self._f: IO[bytes] = open(self._path, "wb")

        # Write file header + all stream headers (biosignals + ECHO markers)
        self._f.write(XDF_MAGIC)
        write_chunk(
            self._f,
            TAG_FILE_HEADER,
            b'<?xml version="1.0"?><info><version>1.0</version></info>',
        )
        for stream_name, stream_id in STREAM_IDS.items():
            xml = _stream_header_xml(
                stream_name,
                session_id,
                participant_id,
                site_id,
                sponsor_id,
            )
            write_chunk(
                self._f,
                TAG_STREAM_HEADER,
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

    def write_marker(self, marker: str, lsl_timestamp: float) -> None:
        """Write one ECHO proximity marker to the XDF marker stream.

        Called before the DB write attempt — if the DB is down this record
        is still preserved in XDF for reconciliation.
        Silently no-ops if already closed. Logs and continues on I/O error.
        """
        if self._closed:
            return

        payload = _build_marker_payload(STREAM_IDS["ECHO"], lsl_timestamp, marker)

        with self._lock:
            if self._closed:
                return
            try:
                write_chunk(self._f, TAG_SAMPLES, payload)
                self._f.flush()
            except OSError as exc:
                log.error(
                    "XDF marker write failed",
                    extra={"marker": marker[:100], "error": str(exc)},
                )
                return

            self._sample_counts["ECHO"] += 1
            if self._first_ts["ECHO"] is None:
                self._first_ts["ECHO"] = lsl_timestamp
            self._last_ts["ECHO"] = lsl_timestamp

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

        payload = _build_biosignal_payload(BIOSIGNAL_STREAM_IDS[stream_name], timestamps, samples)

        with self._lock:
            if self._closed:
                return
            try:
                write_chunk(self._f, TAG_SAMPLES, payload)
                self._f.flush()
            except OSError as exc:
                log.error(
                    "XDF write failed — chunk dropped",
                    extra={"stream_name": stream_name, "error": str(exc)},
                )
                return

            self._sample_counts[stream_name] += len(timestamps)
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

            for stream_name, stream_id in STREAM_IDS.items():
                n = self._sample_counts[stream_name]
                first = self._first_ts[stream_name] or 0.0
                last = self._last_ts[stream_name] or 0.0
                footer_xml = _stream_footer_xml(first, last, n)
                write_chunk(
                    self._f,
                    TAG_STREAM_FOOTER,
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

    @property
    def is_closed(self) -> bool:
        return self._closed
