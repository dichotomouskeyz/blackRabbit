"""XDF vs TimescaleDB reconciliation CLI and compatibility exports.

The implementation is split by responsibility:
  - reconciliation/xdf.py: XDF count/sample/marker readers
  - reconciliation/db.py: DB counts, reports, session metadata/status
  - reconciliation/backfill.py: biosignal and ECHO backfill
  - reconciliation/models.py: shared constants, exceptions, dataclasses

Keep imports from batch.reconcile stable so existing tests and scripts do not
need to know about the internal module split.

## Difference between reconciliation and reconcile ##
    reconcile = the CLI entry point / old import compatibility layer
    reconciliation = the organized implementation package
"""

import argparse
import sys
from pathlib import Path

import psycopg2

from batch.reconciliation.backfill import (
    _build_backfill_rows,
    backfill_echo_markers,
    backfill_stream,
    run_backfill,
)
from batch.reconciliation.db import (
    build_report,
    close_session,
    fetch_existing_echo_keys,
    fetch_existing_echo_timestamps,
    fetch_existing_sample_indices,
    fetch_session_meta,
    query_db_counts,
    query_max_clock_drift_s,
    write_reconciliation_log,
)
from batch.reconciliation.models import (
    _ECHO_STREAM_NAME,
    _STREAM_TABLES,
    _XDF_MAGIC,
    BACKFILL_CHUNK_SIZE_ROWS,
    ReconciliationReport,
    SessionMeta,
    StreamResult,
    XDFReadError,
    XDFTruncatedError,
)
from batch.reconciliation.xdf import (
    _read_chunk_length,
    read_xdf_counts,
    stream_xdf_markers,
    stream_xdf_samples,
)
from capture.logger import get_logger, set_session_id
from config import settings

log = get_logger("reconcile")

__all__ = [
    "BACKFILL_CHUNK_SIZE_ROWS",
    "ReconciliationReport",
    "SessionMeta",
    "StreamResult",
    "XDFReadError",
    "XDFTruncatedError",
    "_ECHO_STREAM_NAME",
    "_STREAM_TABLES",
    "_XDF_MAGIC",
    "_build_backfill_rows",
    "_read_chunk_length",
    "backfill_echo_markers",
    "backfill_stream",
    "build_report",
    "close_session",
    "fetch_existing_echo_timestamps",
    "fetch_existing_echo_keys",
    "fetch_existing_sample_indices",
    "fetch_session_meta",
    "query_db_counts",
    "query_max_clock_drift_s",
    "read_xdf_counts",
    "run_backfill",
    "stream_xdf_markers",
    "stream_xdf_samples",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="untitledplatform_1a XDF to TimescaleDB reconciliation"
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--xdf-path", required=True, type=Path)
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "If gaps are found, replay missing samples from XDF into TimescaleDB, "
            f"then re-reconcile. Commits in chunks of {BACKFILL_CHUNK_SIZE_ROWS} rows."
        ),
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=BACKFILL_CHUNK_SIZE_ROWS,
        metavar="ROWS",
        help="DB rows per commit during backfill (default: %(default)s).",
    )
    return parser.parse_args()


def main() -> None:
    settings.validate()
    args = _parse_args()
    set_session_id(args.session_id)

    log.info(
        "reconciliation starting",
        extra={
            "session_id": args.session_id,
            "xdf_path": str(args.xdf_path),
            "backfill": args.backfill,
        },
    )

    try:
        xdf_counts = read_xdf_counts(args.xdf_path)
    except XDFTruncatedError as exc:
        log.error("XDF file truncated - footers missing", extra={"error": str(exc)})
        sys.exit(2)
    except XDFReadError as exc:
        log.error("XDF file unreadable", extra={"error": str(exc)})
        sys.exit(2)

    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = False
    except psycopg2.OperationalError as exc:
        log.error("DB connection failed", extra={"error": str(exc)})
        sys.exit(2)

    try:
        db_counts = query_db_counts(conn, args.session_id)
        max_clock_drift_s = query_max_clock_drift_s(conn, args.session_id)
        report = build_report(
            args.session_id,
            args.xdf_path,
            xdf_counts,
            db_counts,
            max_clock_drift_s=max_clock_drift_s,
        )
        meta = fetch_session_meta(conn, args.session_id)

        if args.backfill and not report.is_reconciled:
            rows_backfilled = run_backfill(conn, report, meta=meta, chunk_size=args.chunk_size)
            log.info("backfill finished", extra={"rows_backfilled": rows_backfilled})

            db_counts_after = query_db_counts(conn, args.session_id)
            max_clock_drift_s = query_max_clock_drift_s(conn, args.session_id)
            report = build_report(
                args.session_id,
                args.xdf_path,
                xdf_counts,
                db_counts_after,
                max_clock_drift_s=max_clock_drift_s,
            )

        write_reconciliation_log(conn, report, meta)
        close_session(conn, args.session_id, args.sponsor_id, is_reconciled=report.is_reconciled)
    finally:
        conn.close()

    if report.is_reconciled:
        log.info("reconciliation PASSED", extra=report.as_dict())
    else:
        gaps = {name: result.gap for name, result in report.streams.items() if result.gap}
        log.error(
            "reconciliation FAILED - sample gaps detected",
            extra={**report.as_dict(), "streams_with_gaps": gaps},
        )

    sys.exit(0 if report.is_reconciled else 1)


if __name__ == "__main__":
    main()
