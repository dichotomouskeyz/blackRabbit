"""Clock-drift persistence for forwarder streams."""

import time

import pylsl

from capture.forwarder.models import DRIFT_WARN_THRESHOLD_S
from capture.forwarder.sql import _CLOCK_DRIFT_INSERT
from capture.logger import get_logger
from config import settings

log = get_logger("lsl_forwarder")


def maybe_record_drift(thread, now_lsl: float | None = None) -> None:
    """Record clock drift via thread.inlet/thread.conn when the interval elapsed.

    now_lsl overrides the clock for callers/tests that supply their own time.
    Drift persistence is non-negotiable: a due drift record with no DB
    connection raises RuntimeError (fatal - forwarder restarts via watchdog).
    """
    now = now_lsl if now_lsl is not None else time.monotonic()
    if now - thread._last_drift_ts < settings.CLOCK_DRIFT_RECORD_INTERVAL:
        return
    thread._last_drift_ts = now

    if thread.conn is None:
        raise RuntimeError("clock drift must be written to clock_drift_log; DB connection is None")

    try:
        offset_s = thread.inlet.time_correction()
    except Exception as exc:
        log.warning(
            f"{thread.stream_type} clock correction unavailable",
            extra={"error": str(exc)},
        )
        return

    exceeds = abs(offset_s) > DRIFT_WARN_THRESHOLD_S
    write_drift_row(thread, offset_s, exceeds)


def write_drift_row(thread, offset_s: float, exceeds: bool) -> None:
    conn = thread.conn
    try:
        with conn.cursor() as cur:
            cur.execute(
                _CLOCK_DRIFT_INSERT,
                {
                    "session_id": thread.cfg.session_id,
                    "participant_id": thread.cfg.participant_id,
                    "site_id": thread.cfg.site_id,
                    "sponsor_id": thread.cfg.sponsor_id,
                    "device_id": settings.DEVICE_ID,
                    "stream_type": thread.stream_type,
                    "remote_clock_offset_s": round(offset_s, 6),
                    "exceeds_threshold": exceeds,
                    "threshold_s": DRIFT_WARN_THRESHOLD_S,
                    "lsl_timestamp": pylsl.local_clock(),
                },
            )
        conn.commit()
    except Exception as db_exc:
        try:
            conn.rollback()
        except Exception as rb_exc:
            log.debug(
                f"{thread.stream_type} DB rollback failed after clock drift write error",
                extra={"error": str(rb_exc)},
            )
        raise RuntimeError("clock drift write to clock_drift_log failed") from db_exc
