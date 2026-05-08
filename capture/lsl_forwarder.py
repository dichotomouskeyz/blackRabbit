"""Consensai 1a — LSL stream forwarder.

Resolves one inlet per biosignal modality, injects per-sample metadata,
serializes each chunk as a versioned JSON payload, and writes directly to
TimescaleDB. On DB connection drop, samples buffer locally in memory and
flush automatically on reconnect. Clock offsets are recorded at regular
intervals for drift auditing.

Usage:
    python -m capture.lsl_forwarder \\
        --session-id  <uuid> \\
        --participant-id <pseudonymous-token> \\
        --site-id     <uuid> \\
        --sponsor-id  <uuid>

One thread per modality runs independently. Ctrl+C sets the stop event,
all threads flush their buffers, and the process exits cleanly.
"""

import argparse
import collections
import signal
import threading
import time
import uuid
from dataclasses import dataclass

import psycopg2
import psycopg2.extras
import pylsl

from capture.humen_handler import HUMeNThread
from capture.logger import get_logger, set_session_id
from capture.xdf_writer import XDFWriter
from config import settings

settings.validate()

log = get_logger("lsl_forwarder")

# ---------------------------------------------------------------------------
# Versioned payload schema
# Bump PAYLOAD_SCHEMA_VERSION when the structure of per-chunk log payloads
# changes. Written to every significant log line so audit records always
# document which schema version produced the data.
# ---------------------------------------------------------------------------
PAYLOAD_SCHEMA_VERSION = "1.0"

# Max chunks held per modality while DB is unavailable.
# EEG: 200 chunks × 25 samples × 8 ch = 40,000 rows (~16 s at 256 Hz)
BUFFER_MAX_CHUNKS = 200

# Clock offset above this threshold (seconds) triggers a WARNING.
DRIFT_WARN_THRESHOLD_S = 0.100

# Log a throughput summary every N chunks (keeps INFO log readable).
_LOG_EVERY_N_CHUNKS = 50


# ---------------------------------------------------------------------------
# Session config — immutable for the lifetime of one recording
# ---------------------------------------------------------------------------
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

    def __post_init__(self) -> None:
        for field in ("session_id", "participant_id", "site_id", "sponsor_id"):
            _validate_uuid(getattr(self, field), f"SessionConfig.{field}")


# ---------------------------------------------------------------------------
# Per-modality row builders
# Each returns a list of dicts matching the target table's column set.
# EEG is narrow-row: one dict per channel per sample.
# All others return a single dict per sample.
# ---------------------------------------------------------------------------


def _build_eeg_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "channel_id": f"ch_{ch}",
            "voltage": voltage,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
        for ch, voltage in enumerate(sample)
    ]


def _build_hrv_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    rr_ms = sample[0]
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "rr_interval_ms": rr_ms,
            "heart_rate_bpm": 60000.0 / rr_ms if rr_ms > 0 else None,
            "beat_quality": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]


def _build_eda_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    conductance = sample[0]
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "raw_conductance_us": conductance,
            "conductance_us": conductance,  # no filter applied in forwarder
            "signal_quality": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]


def _build_respiration_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    amplitude = sample[0]
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "raw_amplitude": amplitude,
            "processed_amplitude": amplitude,  # no filter applied in forwarder
            "breath_phase": None,
            "breaths_per_min": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]


# ---------------------------------------------------------------------------
# Per-modality INSERT statements (parameterised — no string interpolation)
# ---------------------------------------------------------------------------

_EEG_INSERT = """
    INSERT INTO eeg_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         channel_id, voltage, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(channel_id)s, %(voltage)s, %(lsl_timestamp)s, %(sample_index)s)
"""

_HRV_INSERT = """
    INSERT INTO hrv_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         rr_interval_ms, heart_rate_bpm, beat_quality, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(rr_interval_ms)s, %(heart_rate_bpm)s, %(beat_quality)s,
         %(lsl_timestamp)s, %(sample_index)s)
"""

_EDA_INSERT = """
    INSERT INTO eda_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         raw_conductance_us, conductance_us, signal_quality, lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(raw_conductance_us)s, %(conductance_us)s, %(signal_quality)s,
         %(lsl_timestamp)s, %(sample_index)s)
"""

_RESPIRATION_INSERT = """
    INSERT INTO respiration_samples
        (session_id, participant_id, site_id, sponsor_id, device_id,
         raw_amplitude, processed_amplitude, breath_phase, breaths_per_min,
         lsl_timestamp, sample_index)
    VALUES
        (%(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
         %(raw_amplitude)s, %(processed_amplitude)s, %(breath_phase)s, %(breaths_per_min)s,
         %(lsl_timestamp)s, %(sample_index)s)
"""

_CLOCK_DRIFT_INSERT = """
    INSERT INTO clock_drift_log (
        session_id, participant_id, site_id, sponsor_id, device_id,
        stream_type, remote_clock_offset_s, exceeds_threshold, threshold_s,
        lsl_timestamp
    ) VALUES (
        %(session_id)s, %(participant_id)s, %(site_id)s, %(sponsor_id)s, %(device_id)s,
        %(stream_type)s, %(remote_clock_offset_s)s, %(exceeds_threshold)s, %(threshold_s)s,
        %(lsl_timestamp)s
    )
"""


# ---------------------------------------------------------------------------
# Stream thread
# ---------------------------------------------------------------------------


class _StreamThread(threading.Thread):

    def __init__(
        self,
        stream_name: str,
        stream_type: str,
        chunk_size: int,
        row_builder: callable,
        insert_sql: str,
        cfg: SessionConfig,
        stop_event: threading.Event,
        xdf_writer: XDFWriter,
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
            log.error(f"{self._stream_type} inlet not found — thread exiting")
            return

        conn = self._connect_db()
        if conn is None:
            log.error(
                f"{self._stream_type} could not establish DB connection — thread exiting"
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

            # Write to XDF backup first — the reconciliation source if DB fails
            self._xdf.write_samples(self._stream_type, samples, timestamps)

            # Build rows for entire chunk
            all_rows: list[dict] = []
            for sample, lsl_ts in zip(samples, timestamps):
                all_rows.extend(
                    self._row_builder(sample, self._cfg, lsl_ts, self._sample_index)
                )
                self._sample_index += 1

            self._chunk_count += 1
            if self._chunk_count % _LOG_EVERY_N_CHUNKS == 0:
                self._log_chunk_summary(len(samples), timestamps)

            # Write to DB or buffer on failure
            if conn is not None:
                if self._buffer:
                    conn = self._flush_buffer(conn)
                if conn is not None:
                    conn = self._write_rows(conn, all_rows)

            if conn is None:
                # DB is down — buffer chunk and attempt reconnect
                if len(self._buffer) < BUFFER_MAX_CHUNKS:
                    self._buffer.append(all_rows)
                else:
                    log.error(
                        f"{self._stream_type} buffer full — oldest chunk dropped",
                        extra={
                            "dropped_rows": len(self._buffer[0]),
                            "buffer_depth": len(self._buffer),
                        },
                    )
                    self._buffer.append(all_rows)  # deque drops oldest automatically

                if self._chunk_count % 10 == 0:
                    log.warning(
                        f"{self._stream_type} DB unavailable",
                        extra={
                            "buffered_chunks": len(self._buffer),
                            "max": BUFFER_MAX_CHUNKS,
                        },
                    )
                conn = self._try_reconnect()

        # Shutdown — flush remaining buffer
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        """Connect with exponential backoff. Blocks until connected or stop is set."""
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                conn = psycopg2.connect(settings.DATABASE_URL)
                conn.autocommit = False
                log.info(f"{self._stream_type} DB connection established")
                return conn
            except psycopg2.OperationalError as exc:
                log.warning(
                    f"{self._stream_type} DB connection failed — retrying",
                    extra={"retry_in_s": backoff, "error": str(exc)},
                )
                self._stop_event.wait(backoff)
                backoff = min(backoff * 2, 30.0)
        return None

    def _try_reconnect(self) -> psycopg2.extensions.connection | None:
        """Single reconnect attempt. Returns None without blocking if it fails."""
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
        """Insert rows. Returns conn on success, None on connection failure."""
        try:
            cur = conn.cursor()
            psycopg2.extras.execute_batch(cur, self._insert_sql, rows)
            conn.commit()
            cur.close()
            return conn
        except psycopg2.OperationalError as exc:
            log.error(
                f"{self._stream_type} DB write failed — connection dropped",
                extra={"error": str(exc), "rows_lost_to_buffer": len(rows)},
            )
            try:
                conn.close()
            except Exception:
                pass
            self._buffer.append(rows)
            return None
        except psycopg2.Error as exc:
            # Non-connection error (constraint violation etc.) — log and skip
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
        """Drain local buffer into DB. Returns None if connection drops mid-flush."""
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


# ---------------------------------------------------------------------------
# Pre-flight check
# ---------------------------------------------------------------------------

_REQUIRED_MODALITIES = frozenset({"eeg", "hrv", "eda", "respiration"})


def _verify_session_ready(cfg: SessionConfig) -> None:
    """Confirm the session is valid before any biosignal data is written.

    Raises RuntimeError (non-zero exit, watchdog logs it) if:
      - the sessions row is missing — session_init was never run
      - status != 'active' — session is closed, failed, or still initializing
      - any of the 4 session_signal_metadata rows are absent — session_init
        transaction was interrupted or metadata was manually deleted

    Opens its own short-lived connection so the check is independent of the
    per-thread connections that start later.
    """
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM sessions WHERE id = %s",
                (cfg.session_id,),
            )
            row = cur.fetchone()

        if row is None:
            raise RuntimeError(
                f"Session {cfg.session_id!r} not found — "
                "run session_init before starting the forwarder"
            )

        status = str(row[0])
        if status != "active":
            raise RuntimeError(
                f"Session {cfg.session_id!r} has status {status!r}, expected 'active' — "
                "session is not ready to receive samples"
            )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT modality FROM session_signal_metadata WHERE session_id = %s",
                (cfg.session_id,),
            )
            present = {r[0] for r in cur.fetchall()}

        missing = _REQUIRED_MODALITIES - present
        if missing:
            raise RuntimeError(
                f"Session {cfg.session_id!r} is missing signal metadata for: "
                f"{sorted(missing)} — re-run session_init to rebuild metadata rows"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Consensai LSL forwarder")
    p.add_argument("--session-id", required=True, type=_parse_uuid, help="Session UUID")
    p.add_argument(
        "--participant-id",
        required=True,
        type=_parse_uuid,
        help="Pseudonymous participant UUID",
    )
    p.add_argument("--site-id", required=True, type=_parse_uuid, help="Site UUID")
    p.add_argument("--sponsor-id", required=True, type=_parse_uuid, help="Sponsor UUID")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    cfg = SessionConfig(
        session_id=args.session_id,
        participant_id=args.participant_id,
        site_id=args.site_id,
        sponsor_id=args.sponsor_id,
    )

    set_session_id(cfg.session_id)
    _verify_session_ready(cfg)

    log.info(
        "forwarder starting",
        extra={
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "simulation_mode": settings.SIMULATION_MODE,
        },
    )

    xdf = XDFWriter(
        session_id=cfg.session_id,
        site_id=cfg.site_id,
        sponsor_id=cfg.sponsor_id,
    )

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda sig, frame: stop.set())

    threads = [
        _StreamThread(
            stream_name=settings.LSL_STREAM_EEG,
            stream_type="EEG",
            chunk_size=settings.LSL_CHUNK_EEG,
            row_builder=_build_eeg_rows,
            insert_sql=_EEG_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
        ),
        _StreamThread(
            stream_name=settings.LSL_STREAM_HRV,
            stream_type="HRV",
            chunk_size=settings.LSL_CHUNK_HRV,
            row_builder=_build_hrv_rows,
            insert_sql=_HRV_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
        ),
        _StreamThread(
            stream_name=settings.LSL_STREAM_EDA,
            stream_type="EDA",
            chunk_size=settings.LSL_CHUNK_EDA,
            row_builder=_build_eda_rows,
            insert_sql=_EDA_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
        ),
        _StreamThread(
            stream_name=settings.LSL_STREAM_RESPIRATION,
            stream_type="Respiration",
            chunk_size=settings.LSL_CHUNK_RESPIRATION,
            row_builder=_build_respiration_rows,
            insert_sql=_RESPIRATION_INSERT,
            cfg=cfg,
            stop_event=stop,
            xdf_writer=xdf,
        ),
    ]

    humen_thread = HUMeNThread(cfg=cfg, stop_event=stop, xdf_writer=xdf)
    threads.append(humen_thread)

    for t in threads:
        t.start()

    log.info("all forwarder threads started — press Ctrl+C to stop")

    try:
        while not stop.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutdown requested — flushing buffers")
        stop.set()

    # All threads share the XDF writer — join all before closing it.
    for t in threads:
        t.join(timeout=10.0)

    xdf.close()
    log.info("forwarder stopped")


if __name__ == "__main__":
    main()
