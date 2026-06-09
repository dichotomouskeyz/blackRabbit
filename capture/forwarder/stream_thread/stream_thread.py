"""Per-modality LSL stream forwarding thread."""

import collections
import threading
from collections.abc import Callable

import psycopg2
import pylsl

from capture.forwarder.models import BUFFER_MAX_CHUNKS, SessionConfig
from capture.forwarder.stream_thread.stream_chunks import log_chunk_summary
from capture.forwarder.stream_thread.stream_db import (
    connect_db,
    flush_buffer,
    try_reconnect,
    write_rows,
)
from capture.forwarder.stream_thread.stream_drift import maybe_record_drift
from capture.forwarder.stream_thread.stream_inlet import resolve_inlet
from capture.forwarder.stream_thread.stream_integrity import write_integrity_log
from capture.forwarder.stream_thread.stream_runtime import run_stream_thread
from capture.xdf.writer import XDFWriter


class StreamThread(threading.Thread):
    def __init__(
        self,
        stream_name: str,
        stream_type: str,
        chunk_size: int,
        row_builder: Callable[[list[float], SessionConfig, float, int], list[dict]],
        insert_sql: str,
        cfg: SessionConfig,
        stop_event: threading.Event,
        xdf_writer: XDFWriter,
        table_name: str,
        hash_fields: tuple[str, ...],
        hash_sort_keys: tuple[str, ...],
    ) -> None:
        super().__init__(name=f"fwd_{stream_type.lower()}", daemon=True)
        self._stream_name = stream_name
        self._stream_type = stream_type
        self._chunk_size = chunk_size
        self._row_builder = row_builder
        self._insert_sql = insert_sql
        self._cfg = cfg
        self._stop_event = stop_event
        self._xdf = xdf_writer
        self._table_name = table_name
        self._hash_fields = hash_fields
        self._hash_sort_keys = hash_sort_keys
        self._buffer: collections.deque[list[dict]] = collections.deque(maxlen=BUFFER_MAX_CHUNKS)
        self._sample_index = 0
        self._chunk_count = 0
        self._last_drift_time = 0.0
        self._fatal_error: RuntimeError | None = None

    def run(self) -> None:
        run_stream_thread(self)

    def resolve_inlet(self) -> pylsl.StreamInlet | None:
        return resolve_inlet(self)

    def connect_db(self) -> psycopg2.extensions.connection | None:
        return connect_db(self)

    def try_reconnect(self) -> psycopg2.extensions.connection | None:
        return try_reconnect(self)

    def write_rows(
        self,
        conn: psycopg2.extensions.connection,
        rows: list[dict],
    ) -> psycopg2.extensions.connection | None:
        return write_rows(self, conn, rows)

    def flush_buffer(
        self,
        conn: psycopg2.extensions.connection,
    ) -> psycopg2.extensions.connection | None:
        return flush_buffer(self, conn)

    def maybe_record_drift(
        self,
        inlet: pylsl.StreamInlet,
        conn: psycopg2.extensions.connection | None,
    ) -> None:
        maybe_record_drift(self, inlet, conn)

    def write_integrity_log(
        self,
        cur,
        rows: list[dict],
    ) -> None:
        write_integrity_log(self, cur, rows)

    def log_chunk_summary(self, sample_count: int, timestamps: list[float]) -> None:
        log_chunk_summary(self, sample_count, timestamps)

    @property
    def sample_index(self) -> int:
        return self._sample_index

    @property
    def buffer(self) -> collections.deque[list[dict]]:
        return self._buffer

    @property
    def fatal_error(self) -> RuntimeError | None:
        return self._fatal_error

    _resolve_inlet = resolve_inlet
    _connect_db = connect_db
    _try_reconnect = try_reconnect
    _write_rows = write_rows
    _flush_buffer = flush_buffer
    _maybe_record_drift = maybe_record_drift
    _write_integrity_log = write_integrity_log
    _log_chunk_summary = log_chunk_summary


_StreamThread = StreamThread
