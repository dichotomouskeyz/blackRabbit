"""Per-modality LSL stream forwarding thread."""

import collections
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

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
from capture.logger import get_logger
from capture.xdf.writer import XDFWriter


def _new_buffer() -> collections.deque:
    return collections.deque(maxlen=BUFFER_MAX_CHUNKS)


@dataclass
class StreamThreadState:
    """Mutable per-thread runtime state, separated from static stream config."""

    buffer: collections.deque = field(default_factory=_new_buffer)
    sample_index: int = 0
    chunk_count: int = 0
    last_drift_ts: float = 0.0
    fatal_error: Exception | None = None


class StreamThread(threading.Thread):
    """One LSL→XDF→DB forwarding thread for a single modality.

    Owns its runtime resources: ``conn`` (DB connection, None while down),
    ``inlet`` (LSL inlet), and ``state`` (buffer/counters). Helper modules
    receive the thread and use the public surface only.
    """

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

        self.state = StreamThreadState()
        self.conn: psycopg2.extensions.connection | None = None
        self.inlet: pylsl.StreamInlet | None = None
        self.log = get_logger("lsl_forwarder")

    # -- static config (read-only) ------------------------------------------

    @property
    def stream_name(self) -> str:
        return self._stream_name

    @property
    def stream_type(self) -> str:
        return self._stream_type

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def row_builder(self) -> Callable:
        return self._row_builder

    @property
    def insert_sql(self) -> str:
        return self._insert_sql

    @property
    def cfg(self) -> SessionConfig:
        return self._cfg

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    @property
    def xdf(self) -> XDFWriter:
        return self._xdf

    @property
    def table_name(self) -> str:
        return self._table_name

    @property
    def hash_fields(self) -> tuple[str, ...]:
        return self._hash_fields

    @property
    def hash_sort_keys(self) -> tuple[str, ...]:
        return self._hash_sort_keys

    # -- mutable state (delegates to StreamThreadState) ----------------------
    # The underscore aliases keep helper modules and spec-derived tests that
    # address state by its historical names working against the same storage.

    @property
    def buffer(self) -> collections.deque:
        return self.state.buffer

    @property
    def _buffer(self) -> collections.deque:
        return self.state.buffer

    @property
    def sample_index(self) -> int:
        return self.state.sample_index

    @property
    def _sample_index(self) -> int:
        return self.state.sample_index

    @_sample_index.setter
    def _sample_index(self, value: int) -> None:
        self.state.sample_index = value

    @property
    def chunk_count(self) -> int:
        return self.state.chunk_count

    @property
    def _chunk_count(self) -> int:
        return self.state.chunk_count

    @_chunk_count.setter
    def _chunk_count(self, value: int) -> None:
        self.state.chunk_count = value

    @property
    def _last_drift_ts(self) -> float:
        return self.state.last_drift_ts

    @_last_drift_ts.setter
    def _last_drift_ts(self, value: float) -> None:
        self.state.last_drift_ts = value

    @property
    def fatal_error(self) -> Exception | None:
        return self.state.fatal_error

    def advance_sample_index(self) -> None:
        self.state.sample_index += 1

    def increment_chunk_count(self) -> None:
        self.state.chunk_count += 1

    def mark_drift_recorded(self, now: float) -> None:
        self.state.last_drift_ts = now

    def set_fatal_error(self, exc: Exception) -> None:
        self.state.fatal_error = exc

    # -- actions --------------------------------------------------------------

    def run(self) -> None:
        run_stream_thread(self)

    def resolve_inlet(self) -> pylsl.StreamInlet | None:
        return resolve_inlet(self)

    def connect_db(self) -> psycopg2.extensions.connection | None:
        return connect_db(self)

    def try_reconnect(self) -> psycopg2.extensions.connection | None:
        return try_reconnect(self)

    def write_rows(self, rows: list[dict]) -> psycopg2.extensions.connection | None:
        return write_rows(self, rows)

    def flush_buffer(self) -> psycopg2.extensions.connection | None:
        return flush_buffer(self)

    def maybe_record_drift(self, now_lsl: float | None = None) -> None:
        maybe_record_drift(self, now_lsl=now_lsl)

    def write_integrity_log(self, cur, rows: list[dict]) -> None:
        write_integrity_log(self, cur, rows)

    def log_chunk_summary(self, sample_count: int, timestamps: list[float]) -> None:
        log_chunk_summary(self, sample_count, timestamps)
