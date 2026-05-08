"""Consensai 1a — Session close CLI.

Runs end-of-session reconciliation and transitions the session to 'closed'
(watermark_verified) or 'failed' (watermark_failed).

Prerequisites — MUST be run after the watchdog has stopped the forwarder
-----------------------------------------------------------------------
The correct sequence is:

    1. kill -TERM <watchdog_pid>           # watchdog SIGTERMs the forwarder
    2. wait for watchdog to exit            # forwarder flushes, closes XDF
    3. python -m capture.session_close ...  # reconcile and close

The watchdog sets session status = 'closing' on clean exit.  If the
session is still 'active' when this script runs, the forwarder may still
be writing — the XDF will be incomplete and reconciliation counts will be
wrong.  The script warns loudly in that case but does not block, to
support the development workflow where the forwarder is run directly
without a watchdog.

Steps
-----
1. Validate session exists and is in 'active' or 'closing' state.
   Warn if 'active' (watchdog should have set it to 'closing' first).
2. Transition to 'closing' (idempotent if already there).
3. Read XDF sample counts; read DB sample counts; build reconciliation report.
4. If any stream has positive gap (XDF > DB): run backfill, then re-reconcile.
5. Call close_session — sets status 'closed' or 'failed' and fires the
   sessions_watermark_trigger (migration 024) which writes
   watermark_verified / watermark_failed to audit_events.

Exit codes
----------
0  — session closed; all stream counts reconciled.
1  — reconciliation failed; one or more streams have unresolvable gaps.
     Session status is set to 'failed'.
2  — pre-condition error: session not found, wrong state, DB unreachable,
     or XDF file unreadable.

Usage
-----
    python -m capture.session_close \\
        --session-id <uuid> \\
        --xdf-path   <path/to/session.xdf>
"""

import argparse
import sys
from pathlib import Path

import psycopg2

from batch.reconcile import (
    XDFReadError,
    XDFTruncatedError,
    build_report,
    close_session,
    fetch_session_meta,
    query_db_counts,
    read_xdf_counts,
    run_backfill,
)
from capture.logger import get_logger, set_session_id
from config import settings

settings.validate()

log = get_logger("session_close")

_VALID_ENTRY_STATES = frozenset({"active", "closing"})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Close a Consensai session and gate post-session batch."
    )
    parser.add_argument("--session-id", required=True, help="Session UUID")
    parser.add_argument(
        "--xdf-path",
        required=True,
        type=Path,
        help="Path to the XDF backup file for this session",
    )
    return parser.parse_args()


def _fetch_session_status(conn, session_id: str) -> str | None:
    """Return the current status string, or None if not found."""
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
    return str(row[0]) if row else None


def _set_closing(conn, session_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET status = 'closing' WHERE id = %s AND status = 'active'",
            (session_id,),
        )
    conn.commit()


def run(session_id: str, xdf_path: Path) -> int:
    """Core logic. Returns the exit code."""
    set_session_id(session_id)

    log.info(
        "session_close starting",
        extra={"session_id": session_id, "xdf_path": str(xdf_path)},
    )

    # --- XDF read (before DB connection; fail early if file is broken) ---
    try:
        xdf_counts = read_xdf_counts(xdf_path)
    except XDFTruncatedError as exc:
        log.error("XDF file truncated", extra={"error": str(exc)})
        return 2
    except XDFReadError as exc:
        log.error("XDF file unreadable", extra={"error": str(exc)})
        return 2

    # --- DB connection ---
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = False
    except psycopg2.OperationalError as exc:
        log.error("DB connection failed", extra={"error": str(exc)})
        return 2

    try:
        # --- Validate session state ---
        status = _fetch_session_status(conn, session_id)
        if status is None:
            log.error("session not found", extra={"session_id": session_id})
            return 2
        if status not in _VALID_ENTRY_STATES:
            log.error(
                "session is not in a closeable state",
                extra={"session_id": session_id, "current_status": status},
            )
            return 2

        # --- Transition to 'closing' (idempotent) ---
        if status == "active":
            log.warning(
                "session is still 'active' — watchdog may not have stopped the "
                "forwarder; XDF may be incomplete if capture is still running. "
                "Expected sequence: SIGTERM watchdog → watchdog exits → session_close.",
                extra={"session_id": session_id},
            )
            _set_closing(conn, session_id)
            log.info("session status → closing", extra={"session_id": session_id})

        # --- Build initial reconciliation report ---
        db_counts = query_db_counts(conn, session_id)
        report = build_report(session_id, xdf_path, xdf_counts, db_counts)

        log.info("initial reconciliation", extra=report.as_dict())

        # --- Backfill if any stream has positive gap ---
        if not report.is_reconciled:
            any_positive_gap = any(r.gap > 0 for r in report.streams.values())
            if any_positive_gap:
                meta = fetch_session_meta(conn, session_id)
                backfill_results = run_backfill(conn, report, meta)
                log.info(
                    "backfill finished", extra={"rows_by_stream": backfill_results}
                )

                db_counts_after = query_db_counts(conn, session_id)
                report = build_report(session_id, xdf_path, xdf_counts, db_counts_after)
                log.info("post-backfill reconciliation", extra=report.as_dict())

        # --- Close session; DB trigger fires watermark_verified or watermark_failed ---
        close_session(conn, session_id, report.is_reconciled)

    finally:
        conn.close()

    if report.is_reconciled:
        log.info(
            "session closed — watermark_verified written",
            extra={"session_id": session_id},
        )
        return 0
    else:
        gaps = {k: v.gap for k, v in report.streams.items() if v.gap != 0}
        log.error(
            "session failed — watermark_failed written; manual review required",
            extra={"session_id": session_id, "streams_with_gaps": gaps},
        )
        return 1


def main() -> None:
    args = _parse_args()
    sys.exit(run(args.session_id, args.xdf_path))


if __name__ == "__main__":
    main()
