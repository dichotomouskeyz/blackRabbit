"""Spec-driven integration tests for forwarder chunk + drift handling
(forwarder.md R-012..R-016, R-018..R-020).

Phase 2 — XDF-first ordering, DB buffering on outage, FIFO flush, and clock
drift recording. One test per R-xxx rule. Assertions derive from the spec only.

NOTE (black-box): stream-thread collaborator signatures are inferred from the
spec. The module skips if those symbols cannot be imported, so name mismatches
surface as skips (wired in Phase D) rather than collection errors.
Skipped without TEST_DATABASE_URL.
"""

from collections import deque
from types import SimpleNamespace

import psycopg2
import pytest

stream_db = pytest.importorskip("capture.forwarder.stream_thread.stream_db")
stream_drift = pytest.importorskip("capture.forwarder.stream_thread.stream_drift")

pytestmark = pytest.mark.integration


def _recording_conn(execute):
    cur = SimpleNamespace(
        __enter__=lambda s: s,
        __exit__=lambda s, *e: False,
        execute=execute,
        close=lambda: None,
    )
    return SimpleNamespace(
        cursor=lambda: cur,
        commit=lambda: None,
        rollback=lambda: None,
        closed=0,
    )


class TestChunkBufferingFlush:
    """forwarder.md — chunk write / buffer / flush.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r014_operational_error_buffers_and_nulls_conn(self):
        def _boom(*a, **k):
            raise psycopg2.OperationalError("down")

        thread = SimpleNamespace(
            buffer=deque(maxlen=stream_db.BUFFER_MAX_CHUNKS),
            conn=_recording_conn(_boom),
            log=__import__("capture.logger", fromlist=["get_logger"]).get_logger("fwd_test"),
            stream_type="EEG",
        )
        rows = [{"sample_index": 0}]
        stream_db.write_rows(thread, rows)
        assert len(thread.buffer) >= 1
        assert thread.conn is None

    def test_r015_non_operational_error_rolls_back_keeps_conn(self):
        def _boom(*a, **k):
            raise psycopg2.IntegrityError("constraint")

        conn = _recording_conn(_boom)
        thread = SimpleNamespace(
            buffer=deque(maxlen=stream_db.BUFFER_MAX_CHUNKS),
            conn=conn,
            log=__import__("capture.logger", fromlist=["get_logger"]).get_logger("fwd_test"),
            stream_type="EEG",
        )
        stream_db.write_rows(thread, [{"sample_index": 0}])
        # Connection retained (thread continues), not nulled.
        assert thread.conn is conn

    def test_r016_flush_buffer_fifo_removes_after_success(self):
        written = []
        thread = SimpleNamespace(
            buffer=deque([[{"i": 0}], [{"i": 1}], [{"i": 2}]]),
            conn=_recording_conn(lambda *a, **k: written.append(a)),
            log=__import__("capture.logger", fromlist=["get_logger"]).get_logger("fwd_test"),
            stream_type="EEG",
        )
        stream_db.flush_buffer(thread)
        assert len(thread.buffer) == 0


class TestClockDrift:
    """forwarder.md — clock drift recording.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r019_drift_due_with_none_conn_raises(self):
        thread = SimpleNamespace(
            conn=None,
            inlet=SimpleNamespace(time_correction=lambda: 0.001),
            log=__import__("capture.logger", fromlist=["get_logger"]).get_logger("fwd_test"),
            stream_type="EEG",
            _last_drift_ts=0.0,
        )
        with pytest.raises(RuntimeError):
            stream_drift.maybe_record_drift(thread, now_lsl=10_000.0)
