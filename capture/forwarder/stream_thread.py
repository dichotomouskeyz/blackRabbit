"""Per-modality LSL stream forwarding thread."""

import collections
import hashlib
import threading
import time
from collections.abc import Callable

import psycopg2
import psycopg2.extras
import pylsl

from capture.forwarder.models import (
    BUFFER_MAX_CHUNKS,
    DRIFT_WARN_THRESHOLD_S,
    LOG_EVERY_N_CHUNKS,
    PAYLOAD_SCHEMA_VERSION,
    SessionConfig,
)
from capture.forwarder.sql import _CLOCK_DRIFT_INSERT
from capture.logger import get_logger
from capture.xdf_writer import XDFWriter
from config import settings

log = get_logger("lsl_forwarder")


class _StreamThread(threading.Thread):
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
        self._buffer: collections.deque[list[dict]] = collections.deque(
            maxlen=BUFFER_MAX_CHUNKS
        )
        self._sample_index = 0
        self._chunk_count = 0
        self._last_drift_time = 0.0

    def run(self) -> None:
        log.info(f"{self._stream_type} thread starting")

        inlet = self._resolve_inlet()
        if inlet is None:
            log.error(f"{self._stream_type} inlet not found - thread exiting")
            return

        conn = self._connect_db()
        if conn is None:
            log.error(
                f"{self._stream_type} could not establish DB connection - thread exiting"
            )
            return

        while not self._stop_event.is_set():
            self._maybe_record_drift(inlet, conn)

            samples, timestamps = inlet.pull_chunk(
                timeout=1.0,
                max_samples=self._chunk_size,
            )
            if not samples:
                continue

            self._xdf.write_samples(self._stream_type, samples, timestamps)

            all_rows: list[dict] = []
            for sample, lsl_ts in zip(samples, timestamps):
                all_rows.extend(
                    self._row_builder(sample, self._cfg, lsl_ts, self._sample_index)
                )
                self._sample_index += 1

            self._chunk_count += 1
            if self._chunk_count % LOG_EVERY_N_CHUNKS == 0:
                self._log_chunk_summary(len(samples), timestamps)

            if conn is not None:
                if self._buffer:
                    conn = self._flush_buffer(conn)
                if conn is not None:
                    conn = self._write_rows(conn, all_rows)
                if conn is not None:
                    self._write_integrity_log(conn, all_rows)

            if conn is None:
                if len(self._buffer) < BUFFER_MAX_CHUNKS:
                    self._buffer.append(all_rows)
                else:
                    log.error(
                        f"{self._stream_type} buffer full - oldest chunk dropped",
                        extra={
                            "dropped_rows": len(self._buffer[0]),
                            "buffer_depth": len(self._buffer),
                        },
                    )
                    self._buffer.append(all_rows)

                if self._chunk_count % 10 == 0:
                    log.warning(
                        f"{self._stream_type} DB unavailable",
                        extra={
                            "buffered_chunks": len(self._buffer),
                            "max": BUFFER_MAX_CHUNKS,
                        },
                    )
                conn = self._try_reconnect()

        if conn and self._buffer:
            self._flush_buffer(conn)
        if conn:
            conn.close()
        log.info(
            f"{self._stream_type} thread stopped",
            extra={
                "total_samples": self._sample_index,
                "buffered_chunks_remaining": len(self._buffer),
            },
        )

    def _resolve_inlet(self) -> pylsl.StreamInlet | None:
        log.info(
            f"{self._stream_type} resolving stream",
            extra={
                "stream_name": self._stream_name,
                "timeout_s": settings.LSL_RESOLVE_TIMEOUT,
            },
        )
        streams = pylsl.resolve_byprop(
            "name", self._stream_name, timeout=settings.LSL_RESOLVE_TIMEOUT
        )
        if not streams:
            return None
        inlet = pylsl.StreamInlet(streams[0], max_buflen=int(settings.LSL_MAX_BUFSIZE))
        info = inlet.info()
        log.info(
            f"{self._stream_type} inlet connected",
            extra={
                "stream_name": info.name(),
                "stream_type": info.type(),
                "channels": info.channel_count(),
                "nominal_rate_hz": info.nominal_srate(),
                "source_id": info.source_id(),
                "simulation_mode": settings.SIMULATION_MODE,
            },
        )
        return inlet

    def _connect_db(self) -> psycopg2.extensions.connection | None:
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                conn = psycopg2.connect(settings.DATABASE_URL)
                conn.autocommit = False
                log.info(f"{self._stream_type} DB connection established")
                return conn
            except psycopg2.OperationalError as exc:
                log.warning(
                    f"{self._stream_type} DB connection failed - retrying",
                    extra={"retry_in_s": backoff, "error": str(exc)},
                )
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 30.0)
        return None

    def _try_reconnect(self) -> psycopg2.extensions.connection | None:
        try:
            conn = psycopg2.connect(settings.DATABASE_URL)
            conn.autocommit = False
            log.info(
                f"{self._stream_type} DB reconnected",
                extra={"buffered_chunks": len(self._buffer)},
            )
            return conn
        except psycopg2.OperationalError:
            return None

    def _write_rows(
        self,
        conn: psycopg2.extensions.connection,
        rows: list[dict],
    ) -> psycopg2.extensions.connection | None:
        try:
            cur = conn.cursor()
            psycopg2.extras.execute_batch(cur, self._insert_sql, rows)
            conn.commit()
            cur.close()
            return conn
        except psycopg2.OperationalError as exc:
            log.error(
                f"{self._stream_type} DB write failed - connection dropped",
                extra={"error": str(exc), "rows_lost_to_buffer": len(rows)},
            )
            try:
                conn.close()
            except Exception:
                pass
            self._buffer.append(rows)
            return None
        except psycopg2.Error as exc:
            log.error(
                f"{self._stream_type} DB insert error",
                extra={"error": str(exc), "rows": len(rows)},
            )
            try:
                conn.rollback()
            except Exception:
                pass
            return conn

    def _flush_buffer(
        self,
        conn: psycopg2.extensions.connection,
    ) -> psycopg2.extensions.connection | None:
        flushed = 0
        while self._buffer and conn is not None:
            rows = self._buffer[0]
            conn = self._write_rows(conn, rows)
            if conn is not None:
                self._buffer.popleft()
                flushed += 1
        if flushed:
            log.info(
                f"{self._stream_type} buffer flushed",
                extra={
                    "chunks_flushed": flushed,
                    "chunks_remaining": len(self._buffer),
                },
            )
        return conn

    def _maybe_record_drift(
        self,
        inlet: pylsl.StreamInlet,
        conn: psycopg2.extensions.connection | None,
    ) -> None:
        now = time.monotonic()
        if now - self._last_drift_time < settings.CLOCK_DRIFT_RECORD_INTERVAL:
            return
        self._last_drift_time = now
        try:
            offset_s = inlet.time_correction()
            exceeds = abs(offset_s) > DRIFT_WARN_THRESHOLD_S

            if exceeds:
                log.warning(
                    f"{self._stream_type} clock drift exceeds threshold",
                    extra={
                        "schema_version": PAYLOAD_SCHEMA_VERSION,
                        "remote_clock_offset_s": round(offset_s, 6),
                        "threshold_s": DRIFT_WARN_THRESHOLD_S,
                        "session_id": self._cfg.session_id,
                        "device_id": settings.DEVICE_ID,
                    },
                )
            else:
                log.info(
                    f"{self._stream_type} clock offset recorded",
                    extra={
                        "schema_version": PAYLOAD_SCHEMA_VERSION,
                        "remote_clock_offset_s": round(offset_s, 6),
                        "session_id": self._cfg.session_id,
                        "device_id": settings.DEVICE_ID,
                    },
                )

            if conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            _CLOCK_DRIFT_INSERT,
                            {
                                "session_id": self._cfg.session_id,
                                "participant_id": self._cfg.participant_id,
                                "site_id": self._cfg.site_id,
                                "sponsor_id": self._cfg.sponsor_id,
                                "device_id": settings.DEVICE_ID,
                                "stream_type": self._stream_type,
                                "remote_clock_offset_s": round(offset_s, 6),
                                "exceeds_threshold": exceeds,
                                "threshold_s": DRIFT_WARN_THRESHOLD_S,
                                "lsl_timestamp": pylsl.local_clock(),
                            },
                        )
                    conn.commit()
                except Exception as db_exc:
                    log.error(
                        f"{self._stream_type} clock drift DB write failed",
                        extra={"error": str(db_exc)},
                    )
                    try:
                        conn.rollback()
                    except Exception:
                        pass

        except Exception as exc:
            log.warning(
                f"{self._stream_type} clock correction unavailable",
                extra={"error": str(exc)},
            )

    def _write_integrity_log(
        self,
        conn: psycopg2.extensions.connection,
        rows: list[dict],
    ) -> None:
        try:
            sorted_rows = sorted(
                rows, key=lambda row: tuple(row[key] for key in self._hash_sort_keys)
            )
            hash_input = ",".join(
                "|".join(str(row[field]) for field in self._hash_fields)
                for row in sorted_rows
            )
            chunk_hash = hashlib.md5(hash_input.encode()).hexdigest()
            sample_indices = [row["sample_index"] for row in rows]
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO biosignal_integrity_log
                   (session_id, site_id, sponsor_id, table_name, row_count,
                    min_sample_index, max_sample_index, chunk_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    rows[0]["session_id"],
                    rows[0]["site_id"],
                    rows[0]["sponsor_id"],
                    self._table_name,
                    len(rows),
                    min(sample_indices),
                    max(sample_indices),
                    chunk_hash,
                ),
            )
            conn.commit()
            cur.close()
        except Exception as exc:
            log.warning(
                f"{self._stream_type} integrity log write failed",
                extra={"error": str(exc)},
            )
            try:
                conn.rollback()
            except Exception:
                pass

    def _log_chunk_summary(self, sample_count: int, timestamps: list[float]) -> None:
        log.info(
            f"{self._stream_type} chunk written",
            extra={
                "schema_version": PAYLOAD_SCHEMA_VERSION,
                "stream_type": self._stream_type,
                "session_id": self._cfg.session_id,
                "device_id": settings.DEVICE_ID,
                "simulation_mode": settings.SIMULATION_MODE,
                "samples_in_chunk": sample_count,
                "sample_index_end": self._sample_index - 1,
                "lsl_ts_start": round(timestamps[0], 6) if timestamps else None,
                "lsl_ts_end": round(timestamps[-1], 6) if timestamps else None,
                "buffer_depth": len(self._buffer),
            },
        )
