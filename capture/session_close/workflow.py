"""Verify and close raw capture before any separate batch analysis.

Return 0 for verified capture, 1 for failed reconciliation, or 2 for a
precondition failure. Stop capture before calling this workflow. The shared
session lock prevents closeout while a forwarder still owns the recording.
"""

from pathlib import Path

from batch.reconcile import close_session, fetch_session_meta
from batch.reconciliation.xdf import XDFReadError, validate_xdf_identity
from capture.logger import get_logger, set_session_id
from capture.session_close.db import connect_db, ensure_closing, validate_entry_state
from capture.session_close.reconciliation import exit_code_for_report, reconcile_session
from capture.session_lock import SessionBusyError, acquire_session_lock
from capture.watchdog.db import mark_session_failed
from config import settings

log = get_logger("session_close")


def run(session_id: str, sponsor_id: str, xdf_path: str | Path, *, legacy=False) -> int:
    """Reconcile one complete recording without modifying raw source records."""
    settings.validate()
    xdf_path = Path(xdf_path)
    set_session_id(session_id)
    if not xdf_path.is_file():
        log.error("XDF file is missing", extra={"xdf_path": str(xdf_path)})
        return 2
    conn = connect_db()
    if conn is None:
        return 2
    try:
        try:
            acquire_session_lock(conn, session_id)
            status = validate_entry_state(conn, session_id, sponsor_id)
            if status is None:
                return 2
            meta = fetch_session_meta(conn, session_id, sponsor_id=sponsor_id)
            xdf_counts = validate_xdf_identity(
                xdf_path,
                session_id,
                sponsor_id,
                participant_id=meta.participant_id,
                site_id=meta.site_id,
                legacy=legacy,
            )
        except (XDFReadError, SessionBusyError, ValueError) as exc:
            log.error("session close precondition failed", extra={"error": str(exc)})
            return 2

        try:
            ensure_closing(conn, session_id, sponsor_id, status)
            report = reconcile_session(
                conn,
                session_id,
                xdf_path,
                xdf_counts,
                sponsor_id=sponsor_id,
                legacy=legacy,
            )
            close_session(conn, session_id, sponsor_id, is_reconciled=report.is_reconciled)
            return exit_code_for_report(session_id, report)
        except Exception:
            log.exception("capture reconciliation failed", extra={"session_id": session_id})
            try:
                conn.rollback()
                close_session(conn, session_id, sponsor_id, is_reconciled=False)
            except Exception:
                log.exception("primary terminal-state write failed")
                try:
                    mark_session_failed(session_id, sponsor_id)
                except Exception:
                    log.exception("failed capture could not be persisted; manual recovery required")
            return 1
    finally:
        conn.close()
