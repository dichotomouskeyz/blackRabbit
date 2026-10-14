"""Durable, thread-safe XDF 1.0 capture segments."""

import os
import struct
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from capture.logger import get_logger
from config import settings

from .binary import write_chunk
from .constants import (
    BIOSIGNAL_STREAM_IDS,
    CHANNEL_COUNTS,
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


class XDFWriteError(RuntimeError):
    """Capture cannot proceed because its authoritative XDF write failed."""


class XDFWriter:
    """One exclusively created capture segment; successful writes are fsynced."""

    def __init__(
        self,
        session_id: str,
        participant_id: str,
        site_id: str,
        sponsor_id: str,
        *,
        eeg_channel_names: tuple[str, ...] | None = None,
        device_id: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._lock = threading.Lock()
        self._closed = False
        self._failure: Exception | None = None
        self._sample_counts = dict.fromkeys(STREAM_IDS, 0)
        self._first_ts: dict[str, float | None] = dict.fromkeys(STREAM_IDS)
        self._last_ts: dict[str, float | None] = dict.fromkeys(STREAM_IDS)
        names = eeg_channel_names if eeg_channel_names is not None else settings.EEG_CHANNEL_NAMES
        if names is not None and len(names) != CHANNEL_COUNTS["EEG"]:
            raise ValueError("XDF EEG channel names must match configured channel count")
        headers = {
            name: _stream_header_xml(
                name,
                session_id,
                participant_id,
                site_id,
                sponsor_id,
                eeg_channel_names=names,
                device_id=device_id or settings.DEVICE_ID,
            )
            for name in STREAM_IDS
        }
        xdf_dir = Path(settings.XDF_BACKUP_DIR)
        xdf_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self._path = xdf_dir / f"session_{session_id}_{stamp}_{uuid4().hex[:8]}.xdf"
        self._f = open(self._path, "xb")
        try:
            if self._f.write(XDF_MAGIC) != len(XDF_MAGIC):
                raise OSError("short XDF magic write")
            write_chunk(
                self._f,
                TAG_FILE_HEADER,
                b'<?xml version="1.0"?><info><version>1.0</version></info>',
            )
            for name, stream_id in STREAM_IDS.items():
                write_chunk(
                    self._f,
                    TAG_STREAM_HEADER,
                    struct.pack("<I", stream_id) + headers[name].encode("utf-8"),
                )
            self._sync()
        except OSError as exc:
            self._fail(exc)
        log.info("XDF file opened", extra={"xdf_path": str(self._path), "session_id": session_id})

    def _sync(self) -> None:
        self._f.flush()
        os.fsync(self._f.fileno())

    def _check_open(self) -> None:
        if self._failure is not None:
            raise XDFWriteError("XDF writer has failed; capture cannot continue") from self._failure
        if self._closed:
            raise XDFWriteError("XDF writer is already closed")

    def _fail(self, exc: Exception) -> None:
        self._failure = exc
        try:
            self._f.close()
        except OSError:
            pass
        log.error("XDF write failed", extra={"xdf_path": str(self._path), "error": str(exc)})
        raise XDFWriteError(f"XDF write failed: {exc}") from exc

    def _write_payload(self, stream: str, payload: bytes, timestamps: list[float]) -> None:
        try:
            write_chunk(self._f, TAG_SAMPLES, payload)
            self._sync()
        except OSError as exc:
            self._fail(exc)
        self._sample_counts[stream] += len(timestamps)
        if self._first_ts[stream] is None:
            self._first_ts[stream] = timestamps[0]
        self._last_ts[stream] = timestamps[-1]

    def write_marker(self, marker: str, lsl_timestamp: float) -> None:
        with self._lock:
            self._check_open()
            payload = _build_marker_payload(STREAM_IDS["ECHO"], lsl_timestamp, marker)
            self._write_payload("ECHO", payload, [lsl_timestamp])

    def write_samples(
        self, stream_name: str, samples: list[list[float]], timestamps: list[float]
    ) -> None:
        with self._lock:
            self._check_open()
            if stream_name not in BIOSIGNAL_STREAM_IDS:
                raise ValueError(f"unknown XDF biosignal stream: {stream_name}")
            payload = _build_biosignal_payload(
                BIOSIGNAL_STREAM_IDS[stream_name],
                timestamps,
                samples,
                channel_count=CHANNEL_COUNTS[stream_name],
            )
            if samples:
                self._write_payload(stream_name, payload, timestamps)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._check_open()
            try:
                for name, stream_id in STREAM_IDS.items():
                    first_timestamp = self._first_ts[name]
                    last_timestamp = self._last_ts[name]
                    footer = _stream_footer_xml(
                        first_timestamp if first_timestamp is not None else 0.0,
                        last_timestamp if last_timestamp is not None else 0.0,
                        self._sample_counts[name],
                    )
                    write_chunk(self._f, TAG_STREAM_FOOTER, struct.pack("<I", stream_id) + footer)
                self._sync()
                self._f.close()
            except OSError as exc:
                self._fail(exc)
            self._closed = True
        log.info(
            "XDF file closed",
            extra={
                "xdf_path": str(self._path),
                "session_id": self._session_id,
                "sample_counts": self._sample_counts,
            },
        )

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
