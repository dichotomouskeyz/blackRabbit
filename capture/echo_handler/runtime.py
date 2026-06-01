"""Runtime loop for the ECHO marker thread."""

from capture.echo_handler.parser import parse_echo_marker
from capture.echo_handler.rows import build_echo_row, raw_marker_from_sample
from capture.logger import get_logger
from config import settings

log = get_logger("echo_handler")


def run_echo_thread(thread) -> None:
    import pylsl  # deferred so import errors don't kill other threads

    log.info("ECHO thread starting")
    inlet = thread.resolve_inlet(pylsl)
    if inlet is None:
        log.warning(
            "ECHO marker stream not found — thread exiting; "
            "no proximity events will be recorded for this session",
            extra={"stream_name": settings.LSL_STREAM_MARKER},
        )
        return

    conn = thread.connect_db()
    if conn is None:
        log.error("ECHO could not establish DB connection — thread exiting")
        return

    failure_rounds = 0

    while not thread._stop_event.is_set():
        if thread._db_disabled:
            _pull_and_write_xdf_only(thread, inlet)
            continue

        prev_conn = conn
        conn = process_next_sample(thread, inlet, conn)

        if prev_conn is not None and conn is None:
            failure_rounds += 1
            conn = thread.handle_write_failure(failure_rounds)
            if conn is not None:
                failure_rounds = 0

    if conn and thread._buffer:
        thread.flush_buffer(conn)
    if conn:
        conn.close()
    log.info("ECHO thread stopped", extra={"total_events": thread._event_count})


def _pull_and_write_xdf_only(thread, inlet) -> None:
    sample, lsl_ts = inlet.pull_sample(timeout=1.0)
    raw = raw_marker_from_sample(sample)
    if raw is None:
        return

    parsed = parse_echo_marker(raw)
    if parsed is None:
        log.warning("ECHO unrecognised marker — skipped", extra={"raw_marker": raw[:200]})
        return

    log_event(thread._cfg.session_id, parsed, lsl_ts)
    thread._xdf.write_marker(raw, lsl_ts)


def process_next_sample(thread, inlet, conn):
    sample, lsl_ts = inlet.pull_sample(timeout=1.0)
    raw = raw_marker_from_sample(sample)
    if raw is None:
        return conn

    parsed = parse_echo_marker(raw)
    if parsed is None:
        log.warning(
            "ECHO unrecognised marker — skipped",
            extra={"raw_marker": raw[:200]},
        )
        return conn

    row = build_echo_row(thread._cfg, parsed, lsl_ts)
    log_event(thread._cfg.session_id, parsed, lsl_ts)
    thread._xdf.write_marker(raw, lsl_ts)

    conn = thread.write_or_buffer(conn, row)
    if conn is None:
        conn = thread.try_reconnect()
    return conn


def log_event(session_id: str, parsed: dict[str, str], lsl_ts: float) -> None:
    log.info(
        "ECHO event",
        extra={
            "event_type": parsed["event_type"],
            "zone_label": parsed["zone_label"],
            "actor_id": parsed["actor_id"],
            "actor_role": parsed["actor_role"],
            "lsl_timestamp": round(lsl_ts, 6),
            "session_id": session_id,
        },
    )
