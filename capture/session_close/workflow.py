"""Session close workflow.

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
        --sponsor-id <uuid> \\
        --xdf-path   <path/to/session.xdf>
"""

from pathlib import Path

from batch.reconcile import close_session
from capture.logger import get_logger, set_session_id
from capture.session_close.db import connect_db, ensure_closing, validate_entry_state
from capture.session_close.reconciliation import (
    exit_code_for_report,
    read_xdf_counts_or_none,
    reconcile_session,
)
from config import settings

settings.validate()

log = get_logger("session_close")


def run(session_id: str, sponsor_id: str, xdf_path: Path) -> int:
    """Core logic. Returns the exit code."""
    set_session_id(session_id)

    log.info(
        "session_close starting",
        extra={"session_id": session_id, "sponsor_id": sponsor_id, "xdf_path": str(xdf_path)},
    )

    # XDF read happens before DB connection so broken files fail early.
    xdf_counts = read_xdf_counts_or_none(xdf_path)
    if xdf_counts is None:
        return 2

    conn = connect_db()
    if conn is None:
        return 2

    try:
        status = validate_entry_state(conn, session_id, sponsor_id)
        if status is None:
            return 2

        ensure_closing(conn, session_id, sponsor_id, status)
        report = reconcile_session(conn, session_id, xdf_path, xdf_counts)
        close_session(conn, session_id, report.is_reconciled)

    finally:
        conn.close()

    return exit_code_for_report(session_id, report)
