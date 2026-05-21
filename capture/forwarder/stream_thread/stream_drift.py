"""Clock-drift persistence for forwarder streams."""

import time

import pylsl

from capture.forwarder.models import DRIFT_WARN_THRESHOLD_S
from capture.forwarder.sql import _CLOCK_DRIFT_INSERT
from capture.logger import get_logger
from config import settings

log = get_logger("lsl_forwarder")


def maybe_record_drift(thread, inlet: pylsl.StreamInlet, conn) -> None:
    now = time.monotonic()
    if now - thread._last_drift_time < settings.CLOCK_DRIFT_RECORD_INTERVAL:
        return
    thread._last_drift_time = now

    if conn is None:
        raise RuntimeError("clock drift must be written to clock_drift_log; DB connection is None")

    try:
        offset_s = inlet.time_correction()
    except Exception as exc:
        log.warning(
            f"{thread._stream_type} clock correction unavailable",
            extra={"error": str(exc)},
        )
        return

    exceeds = abs(offset_s) > DRIFT_WARN_THRESHOLD_S
    write_drift_row(thread, conn, offset_s, exceeds)


def write_drift_row(thread, conn, offset_s: float, exceeds: bool) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                _CLOCK_DRIFT_INSERT,
                {
                    "session_id": thread._cfg.session_id,
                    "participant_id": thread._cfg.participant_id,
                    "site_id": thread._cfg.site_id,
                    "sponsor_id": thread._cfg.sponsor_id,
                    "device_id": settings.DEVICE_ID,
                    "stream_type": thread._stream_type,
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
                f"{thread._stream_type} DB rollback failed after clock drift write error",
                extra={"error": str(rb_exc)},
            )
        raise RuntimeError("clock drift write to clock_drift_log failed") from db_exc
