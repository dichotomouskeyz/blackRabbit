"""Session-close package and compatibility exports."""

from batch.reconcile import close_session
from capture.session_close import reconciliation as _reconciliation
from capture.session_close.cli import main
from capture.session_close.cli import parse_args as _parse_args
from capture.session_close.db import (
    connect_db as _connect_db,
)
from capture.session_close.db import (
    ensure_closing as _ensure_closing,
)
from capture.session_close.db import (
    fetch_session_status as _fetch_session_status,
)
from capture.session_close.db import (
    set_closing as _set_closing,
)
from capture.session_close.db import (
    validate_entry_state as _validate_entry_state,
)
from capture.session_close.reconciliation import (
    build_report,
    fetch_session_meta,
    query_db_counts,
    read_xdf_counts,
    run_backfill,
)
from capture.session_close.reconciliation import (
    exit_code_for_report as _exit_code_for_report,
)
from capture.session_close.reconciliation import (
    read_xdf_counts_or_none as _read_xdf_counts_or_none,
)
from capture.session_close.reconciliation import (
    reconcile_session as _reconcile_session,
)
from capture.session_close.workflow import run as _run
from config import settings

XDFReadError = _reconciliation.XDFReadError
XDFTruncatedError = _reconciliation.XDFTruncatedError


def _sync_compat_patches() -> None:
    _reconciliation.read_xdf_counts = read_xdf_counts
    _reconciliation.query_db_counts = query_db_counts
    _reconciliation.build_report = build_report
    _reconciliation.fetch_session_meta = fetch_session_meta
    _reconciliation.run_backfill = run_backfill


def run(session_id, xdf_path):
    _sync_compat_patches()
    return _run(session_id, xdf_path)


__all__ = [
    "XDFReadError",
    "XDFTruncatedError",
    "_connect_db",
    "_ensure_closing",
    "_exit_code_for_report",
    "_fetch_session_status",
    "_parse_args",
    "_read_xdf_counts_or_none",
    "_reconcile_session",
    "_set_closing",
    "_validate_entry_state",
    "build_report",
    "close_session",
    "fetch_session_meta",
    "main",
    "query_db_counts",
    "read_xdf_counts",
    "run",
    "run_backfill",
    "settings",
]
