"""Spec-driven unit tests for session_close (session-close.md R-001..R-008).

Phase 2 — state machine + XDF-read guards. No live DB; DB-reading helpers
are exercised with injected fake connections / monkeypatched readers.
Assertions derive from the spec text only.

NOTE (black-box): helper signatures are inferred from the spec. Phase D
resolves any mismatch in the call sites only.
"""

from types import SimpleNamespace

import pytest

import capture.session_close.db as scdb
import capture.session_close.reconciliation as screcon
from capture.session_close.db import ensure_closing, validate_entry_state
from capture.session_close.reconciliation import (
    exit_code_for_report,
    read_xdf_counts_or_none,
)


class _Cursor:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return self._row

    def close(self):
        return None


class _Conn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _Cursor(self._row)


class TestStateMachine:
    """session-close.md — state machine.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize("status", ["active", "closing"])
    def test_r001_returns_status_when_closeable(self, status):
        conn = _Conn((status,))
        assert validate_entry_state(conn, "sid", "spid") == status

    @pytest.mark.parametrize("status", ["closed", "failed", "initializing"])
    def test_r002_returns_none_for_non_entry_states(self, status):
        conn = _Conn((status,))
        assert validate_entry_state(conn, "sid", "spid") is None

    def test_r003_ensure_closing_calls_set_closing_when_active(self, monkeypatch):
        calls = []
        monkeypatch.setattr(scdb, "set_closing", lambda *a, **k: calls.append(a))
        ensure_closing(_Conn(("active",)), "sid", "spid", "active")
        assert len(calls) == 1

    def test_r004_ensure_closing_noop_when_already_closing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(scdb, "set_closing", lambda *a, **k: calls.append(a))
        ensure_closing(_Conn(("closing",)), "sid", "spid", "closing")
        assert calls == []


class TestExitCode:
    """session-close.md — exit code for report.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r005_reconciled_returns_zero(self):
        report = SimpleNamespace(is_reconciled=True, streams={})
        assert exit_code_for_report("sid", report) == 0

    def test_r006_unreconciled_returns_one(self):
        report = SimpleNamespace(
            is_reconciled=False,
            streams={"EEG": SimpleNamespace(gap=5, xdf_count=10, db_count=5)},
        )
        assert exit_code_for_report("sid", report) == 1


class TestXDFReadGuard:
    """session-close.md — XDF read guard.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r007_truncated_returns_none(self, monkeypatch):
        from batch.reconciliation.xdf import XDFTruncatedError

        def _raise(*args, **kwargs):
            raise XDFTruncatedError("never closed")

        monkeypatch.setattr(screcon, "read_xdf_counts", _raise)
        assert read_xdf_counts_or_none("some.xdf") is None

    def test_r008_read_error_returns_none(self, monkeypatch):
        from batch.reconciliation.xdf import XDFReadError

        def _raise(*args, **kwargs):
            raise XDFReadError("bad magic")

        monkeypatch.setattr(screcon, "read_xdf_counts", _raise)
        assert read_xdf_counts_or_none("some.xdf") is None
