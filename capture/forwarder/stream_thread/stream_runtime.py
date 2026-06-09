"""Runtime loop for a single forwarder stream thread."""

from capture.forwarder.stream_thread.stream_chunks import process_chunk
from capture.logger import get_logger

log = get_logger("lsl_forwarder")


def _run_stream_thread_inner(thread) -> None:
    log.info(f"{thread._stream_type} thread starting")

    inlet = thread.resolve_inlet()
    if inlet is None:
        log.error(f"{thread._stream_type} inlet not found - thread exiting")
        return

    conn = thread.connect_db()
    if conn is None:
        log.error(f"{thread._stream_type} could not establish DB connection - thread exiting")
        return

    try:
        while not thread._stop_event.is_set():
            thread.maybe_record_drift(inlet, conn)
            samples, timestamps = inlet.pull_chunk(
                timeout=1.0,
                max_samples=thread._chunk_size,
            )
            if samples:
                conn = process_chunk(thread, conn, samples, timestamps)
    finally:
        if conn and thread.buffer:
            thread.flush_buffer(conn)
        if thread.buffer:
            rows_at_risk = sum(len(chunk) for chunk in thread.buffer)
            log.error(
                f"{thread._stream_type} thread stopped with buffered data at risk",
                extra={
                    "stream_type": thread._stream_type,
                    "buffered_chunks_remaining": len(thread.buffer),
                    "rows_at_risk": rows_at_risk,
                },
            )
        if conn:
            conn.close()
        log.info(
            f"{thread._stream_type} thread stopped",
            extra={
                "total_samples": thread.sample_index,
                "buffered_chunks_remaining": len(thread.buffer),
            },
        )


def run_stream_thread(thread) -> None:
    # Wrap the inner loop so a non-negotiable failure (e.g., clock drift write
    # required by capture/forwarder/stream_thread/stream_drift.py:22,64) does
    # not silently kill this thread and leave the forwarder running in a
    # degraded state. We log CRITICAL with enough context to triage, then set
    # the shared stop_event so sibling stream threads also wind down cleanly.
    # The watchdog observes the forwarder exit and restarts the process.
    try:
        _run_stream_thread_inner(thread)
    except RuntimeError as exc:
        thread._fatal_error = exc
        log.critical(
            f"{thread._stream_type} thread shutting down forwarder after fatal RuntimeError",
            extra={
                "stream_type": thread._stream_type,
                "error": str(exc),
                "sample_index": thread._sample_index,
            },
        )
        thread._stop_event.set()
