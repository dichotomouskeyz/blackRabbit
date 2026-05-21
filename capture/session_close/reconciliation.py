"""XDF/Timescale reconciliation helpers for session close."""

from pathlib import Path

from batch.reconcile import (
    XDFReadError,
    XDFTruncatedError,
    build_report,
    fetch_session_meta,
    query_db_counts,
    query_max_clock_drift_s,
    read_xdf_counts,
    run_backfill,
)
from batch.reconciliation.db import write_reconciliation_log
from capture.logger import get_logger

log = get_logger("session_close")


def read_xdf_counts_or_none(xdf_path: Path) -> dict | None:
    try:
        return read_xdf_counts(xdf_path)
    except XDFTruncatedError as exc:
        log.error("XDF file truncated", extra={"error": str(exc)})
        return None
    except XDFReadError as exc:
        log.error("XDF file unreadable", extra={"error": str(exc)})
        return None


def reconcile_session(conn, session_id: str, xdf_path: Path, xdf_counts: dict):
    db_counts = query_db_counts(conn, session_id)
    max_clock_drift_s = query_max_clock_drift_s(conn, session_id)
    report = build_report(
        session_id,
        xdf_path,
        xdf_counts,
        db_counts,
        max_clock_drift_s=max_clock_drift_s,
    )

    log.info("initial reconciliation", extra=report.as_dict())
    meta = fetch_session_meta(conn, session_id)

    if not report.is_reconciled:
        any_positive_gap = any(row.gap > 0 for row in report.streams.values())
        if any_positive_gap:
            backfill_results = run_backfill(conn, report, meta)
            log.info("backfill finished", extra={"rows_by_stream": backfill_results})

            db_counts_after = query_db_counts(conn, session_id)
            max_clock_drift_s = query_max_clock_drift_s(conn, session_id)
            report = build_report(
                session_id,
                xdf_path,
                xdf_counts,
                db_counts_after,
                max_clock_drift_s=max_clock_drift_s,
            )
            log.info("post-backfill reconciliation", extra=report.as_dict())

    write_reconciliation_log(conn, meta, report)
    return report


def exit_code_for_report(session_id: str, report) -> int:
    if report.is_reconciled:
        log.info(
            "session closed — watermark_verified written",
            extra={"session_id": session_id},
        )
        return 0

    gaps = {key: row.gap for key, row in report.streams.items() if row.gap != 0}
    log.error(
        "session failed — watermark_failed written; manual review required",
        extra={"session_id": session_id, "streams_with_gaps": gaps},
    )
    return 1
