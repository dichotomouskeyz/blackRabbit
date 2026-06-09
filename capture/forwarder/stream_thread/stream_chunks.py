"""Chunk processing helpers for forwarder stream threads."""

from capture.forwarder.models import BUFFER_MAX_CHUNKS, LOG_EVERY_N_CHUNKS, PAYLOAD_SCHEMA_VERSION
from capture.logger import get_logger
from config import settings

log = get_logger("lsl_forwarder")


def process_chunk(thread, conn, samples: list, timestamps: list[float]):
    thread._xdf.write_samples(thread._stream_type, samples, timestamps)
    rows = build_rows(thread, samples, timestamps)

    thread._chunk_count += 1
    if thread._chunk_count % LOG_EVERY_N_CHUNKS == 0:
        log_chunk_summary(thread, len(samples), timestamps)

    if conn is not None:
        conn = write_rows_and_integrity(thread, conn, rows)
    if conn is None:
        buffer_chunk(thread, rows)
        conn = thread.try_reconnect()
    return conn


def build_rows(thread, samples: list, timestamps: list[float]) -> list[dict]:
    rows: list[dict] = []
    for sample, lsl_ts in zip(samples, timestamps):
        rows.extend(thread._row_builder(sample, thread._cfg, lsl_ts, thread._sample_index))
        thread._sample_index += 1
    return rows


def write_rows_and_integrity(thread, conn, rows: list[dict]):
    if thread._buffer:
        conn = thread.flush_buffer(conn)
    if conn is not None:
        conn = thread.write_rows(conn, rows)
    return conn


def buffer_chunk(thread, rows: list[dict]) -> None:
    if len(thread._buffer) < BUFFER_MAX_CHUNKS:
        thread._buffer.append(rows)
    else:
        dropped_rows = len(thread._buffer[0])
        thread._buffer.append(rows)
        log.error(
            f"{thread._stream_type} buffer full - oldest chunk dropped",
            extra={
                "dropped_rows": dropped_rows,
                "buffer_depth": len(thread._buffer),
            },
        )

    if thread._chunk_count % 10 == 0:
        log.warning(
            f"{thread._stream_type} DB unavailable",
            extra={"buffered_chunks": len(thread._buffer), "max": BUFFER_MAX_CHUNKS},
        )


def log_chunk_summary(thread, sample_count: int, timestamps: list[float]) -> None:
    log.info(
        f"{thread._stream_type} chunk written",
        extra={
            "schema_version": PAYLOAD_SCHEMA_VERSION,
            "stream_type": thread._stream_type,
            "session_id": thread._cfg.session_id,
            "device_id": settings.DEVICE_ID,
            "simulation_mode": settings.SIMULATION_MODE,
            "samples_in_chunk": sample_count,
            "sample_index_end": thread._sample_index - 1,
            "lsl_ts_start": round(timestamps[0], 6) if timestamps else None,
            "lsl_ts_end": round(timestamps[-1], 6) if timestamps else None,
            "buffer_depth": len(thread._buffer),
        },
    )
