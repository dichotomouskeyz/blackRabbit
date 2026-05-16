"""Runtime loop for a single forwarder stream thread."""

from capture.forwarder.stream_thread.stream_chunks import process_chunk
from capture.logger import get_logger

log = get_logger("lsl_forwarder")


def run_stream_thread(thread) -> None:
    log.info(f"{thread._stream_type} thread starting")

    inlet = thread._resolve_inlet()
    if inlet is None:
        log.error(f"{thread._stream_type} inlet not found - thread exiting")
        return

    conn = thread._connect_db()
    if conn is None:
        log.error(f"{thread._stream_type} could not establish DB connection - thread exiting")
        return

    while not thread._stop_event.is_set():
        thread._maybe_record_drift(inlet, conn)
        samples, timestamps = inlet.pull_chunk(
            timeout=1.0,
            max_samples=thread._chunk_size,
        )
        if samples:
            conn = process_chunk(thread, conn, samples, timestamps)

    if conn and thread._buffer:
        thread._flush_buffer(conn)
    if conn:
        conn.close()
    log.info(
        f"{thread._stream_type} thread stopped",
        extra={
            "total_samples": thread._sample_index,
            "buffered_chunks_remaining": len(thread._buffer),
        },
    )
