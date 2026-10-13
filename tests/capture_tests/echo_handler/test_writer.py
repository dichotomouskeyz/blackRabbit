"""Spec-driven tests for ECHOWriter buffering (echo-handler.md R-013..R-015).

Phase 2 — `ECHOWriter` buffer + flush. All unit tests; no live DB.
Assertions derive from the spec text only.

NOTE (black-box): ECHOWriter construction and flush signature are inferred
from the spec. Phase D resolves any mismatch in `_writer` / call sites only.
"""

import psycopg2

from capture.echo_handler.writer import BUFFER_MAX, ECHOWriter


def _writer():
    return ECHOWriter()


def _row(i):
    return {"lsl_timestamp": float(i), "event_type": "manual_marker"}


class _Cursor:
    def __init__(self, fail_after):
        self.fail_after = fail_after
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        self.calls += 1
        if self.calls > self.fail_after:
            raise psycopg2.OperationalError("connection dropped")


class _Conn:
    def __init__(self, fail_after):
        self._cursor = _Cursor(fail_after)

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass


class TestECHOWriter:
    """echo-handler.md — ECHOWriter.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r013_buffer_row_appends_when_not_full(self):
        writer = _writer()
        writer.buffer_row(_row(1))
        assert len(writer.buffer) == 1

    def test_r014_buffer_row_overflow_drops_oldest(self):
        writer = _writer()
        for i in range(BUFFER_MAX):
            writer.buffer_row(_row(i))
        oldest = writer.buffer[0]
        writer.buffer_row(_row(9999))
        assert len(writer.buffer) == BUFFER_MAX
        assert writer.buffer[0] is not oldest

    def test_r015_flush_stops_on_connection_drop(self):
        writer = _writer()
        for i in range(3):
            writer.buffer_row(_row(i))
        conn = _Conn(fail_after=1)
        writer.flush_buffer(conn)
        # First row written and removed; flush stops at the drop, rest remain.
        assert len(writer.buffer) == 2
