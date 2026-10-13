"""Runtime loop for a single forwarder stream thread."""

from capture.forwarder.stream_thread.stream_chunks import process_chunk
from capture.logger import get_logger

log = get_logger("lsl_forwarder")


def _run_stream_thread_inner(thread) -> None:
    log.info(f"{thread.stream_type} thread starting")

    thread.inlet = thread.resolve_inlet()
    if thread.inlet is None:
        raise RuntimeError(f"required {thread.stream_type} inlet not found")

    thread.connect_db()
    if thread.conn is None:
        raise RuntimeError(f"required {thread.stream_type} initial DB connection failed")

    try:
        while not thread.stop_event.is_set():
            thread.maybe_record_drift()
            samples, timestamps = thread.inlet.pull_chunk(
                timeout=1.0,
                max_samples=thread.chunk_size,
            )
            if samples:
                process_chunk(thread, samples, timestamps)
    finally:
        if thread.conn is not None and thread.buffer:
            thread.flush_buffer()
        if thread.buffer:
            rows_at_risk = sum(len(chunk) for chunk in thread.buffer)
            log.error(
                f"{thread.stream_type} thread stopped with buffered data at risk",
                extra={
                    "stream_type": thread.stream_type,
                    "buffered_chunks_remaining": len(thread.buffer),
                    "rows_at_risk": rows_at_risk,
                },
            )
        if thread.conn is not None:
            thread.conn.close()
            thread.conn = None
        log.info(
            f"{thread.stream_type} thread stopped",
            extra={
                "total_samples": thread.sample_index,
                "buffered_chunks_remaining": len(thread.buffer),
            },
        )


def run_stream_thread(thread) -> None:
    # Wrap the inner loop so a non-negotiable failure (e.g., the clock drift
    # write required by stream_drift.py) does not silently kill this thread
    # and leave the forwarder running in a degraded state. We log CRITICAL
    # with enough context to triage, then set the shared stop_event so sibling
    # stream threads also wind down cleanly. The watchdog observes the
    # forwarder exit and restarts the process.
    try:
        _run_stream_thread_inner(thread)
    except Exception as exc:
        thread.set_fatal_error(exc)
        log.critical(
            f"{thread.stream_type} thread shutting down forwarder after fatal error",
            extra={
                "stream_type": thread.stream_type,
                "error": str(exc),
                "sample_index": thread.sample_index,
            },
        )
        thread.stop_event.set()
