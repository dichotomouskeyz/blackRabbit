"""Unit tests for ECHO ingestion pipeline logging and DB write behavior."""

import threading
from unittest.mock import MagicMock, patch

import psycopg2

import capture.echo_handler.db as db
from capture.echo_handler.runtime import _pull_and_write_xdf_only, process_next_sample
from capture.echo_handler.thread import ECHOThread


def _echo_row() -> dict:
    return {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "participant_id": "22222222-2222-2222-2222-222222222222",
        "site_id": "33333333-3333-3333-3333-333333333333",
        "sponsor_id": "44444444-4444-4444-4444-444444444444",
        "event_type": "zone_enter",
        "actor_id": "therapist_01",
        "actor_role": "therapist",
        "zone_label": "arms_reach",
        "lsl_timestamp": 123.456,
    }


class _Cursor:
    def __init__(self):
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, row):
        self.executed.append((sql, row))


class _Connection:
    def __init__(self):
        self.cursor_obj = _Cursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


class _FailingCursor:
    """Cursor that raises psycopg2.DataError on the first `fail_times` execute calls."""

    def __init__(self, fail_times: int):
        self._fail_times = fail_times
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, row):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise psycopg2.DataError("synthetic transient error")


class _FailingConnection:
    def __init__(self, fail_times: int):
        self._cursor = _FailingCursor(fail_times)
        self.committed = False
        self.rollback_count = 0
        self.closed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


def _make_thread(on_write_failure=None):
    cfg = MagicMock()
    cfg.session_id = "11111111-1111-1111-1111-111111111111"
    stop = threading.Event()
    thread = ECHOThread(
        cfg=cfg,
        stop_event=stop,
        xdf_writer=MagicMock(),
        on_write_failure=on_write_failure,
    )
    return thread, stop


# ---------------------------------------------------------------------------
# write_row — success and structured log
# ---------------------------------------------------------------------------

def test_write_row_persists_and_logs_structured_event():
    conn = _Connection()
    row = _echo_row()

    with patch.object(db.log, "info") as info:
        returned_conn, wrote = db.write_row(conn, row)

    assert returned_conn is conn
    assert wrote is True
    assert conn.committed is True
    assert conn.cursor_obj.executed[0][1] == row

    info.assert_called_once()
    (message,) = info.call_args.args
    assert message == "ECHO event persisted"
    extra = info.call_args.kwargs["extra"]
    assert extra["session_id"] == row["session_id"]
    assert extra["event_type"] == "zone_enter"
    assert extra["actor_role"] == "therapist"
    assert extra["zone_label"] == "arms_reach"
    assert extra["lsl_timestamp"] == 123.456
    assert extra["ingestion_path"] == "live_db"


# ---------------------------------------------------------------------------
# write_row — retry behavior
# ---------------------------------------------------------------------------

class TestWriteRowRetry:
    def test_retries_on_transient_error_and_succeeds(self):
        # Fails on first attempt, succeeds on second.
        conn = _FailingConnection(fail_times=1)

        with patch("capture.echo_handler.db.time.sleep"):
            returned_conn, wrote = db.write_row(conn, _echo_row())

        assert wrote is True
        assert returned_conn is conn
        assert conn.committed is True
        assert conn.rollback_count == 1

    def test_exhausts_retries_then_closes_connection(self):
        conn = _FailingConnection(fail_times=db.WRITE_MAX_RETRIES)

        with patch("capture.echo_handler.db.time.sleep"):
            returned_conn, wrote = db.write_row(conn, _echo_row())

        assert wrote is False
        assert returned_conn is None
        assert conn.closed is True
        assert conn.rollback_count == db.WRITE_MAX_RETRIES

    def test_operational_error_closes_immediately_without_retry(self):
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = (
            psycopg2.OperationalError("connection lost")
        )

        with patch("capture.echo_handler.db.time.sleep") as sleep:
            returned_conn, wrote = db.write_row(conn, _echo_row())

        assert wrote is False
        assert returned_conn is None
        sleep.assert_not_called()  # no delay between retries — immediate drop

    def test_sleep_called_between_retries(self):
        conn = _FailingConnection(fail_times=db.WRITE_MAX_RETRIES - 1)

        with patch("capture.echo_handler.db.time.sleep") as sleep:
            db.write_row(conn, _echo_row())

        assert sleep.call_count == db.WRITE_MAX_RETRIES - 1
        sleep.assert_called_with(db.WRITE_RETRY_DELAY_S)


# ---------------------------------------------------------------------------
# handle_write_failure — prompt responses
# ---------------------------------------------------------------------------

class TestHandleWriteFailure:
    def test_round1_retry_reconnects_and_returns_conn(self):
        thread, stop = _make_thread(on_write_failure=lambda _round: "retry")
        fake_conn = MagicMock()
        thread.connect_db = MagicMock(return_value=fake_conn)

        result = thread.handle_write_failure(1)

        assert result is fake_conn
        assert thread._db_disabled is False
        assert not stop.is_set()

    def test_round1_no_retry_disables_db_writes(self):
        thread, stop = _make_thread(on_write_failure=lambda _round: "continue")

        result = thread.handle_write_failure(1)

        assert result is None
        assert thread._db_disabled is True
        assert not stop.is_set()

    def test_round2_cancel_sets_stop_event(self):
        thread, stop = _make_thread(on_write_failure=lambda _round: "cancel")

        result = thread.handle_write_failure(2)

        assert result is None
        assert stop.is_set()

    def test_round2_continue_disables_db_writes(self):
        thread, stop = _make_thread(on_write_failure=lambda _round: "continue")

        result = thread.handle_write_failure(2)

        assert result is None
        assert thread._db_disabled is True
        assert not stop.is_set()

    def test_successful_retry_conn_is_returned(self):
        fake_conn = object()
        thread, _ = _make_thread(on_write_failure=lambda _round: "retry")
        thread.connect_db = MagicMock(return_value=fake_conn)

        result = thread.handle_write_failure(1)

        assert result is fake_conn


# ---------------------------------------------------------------------------
# run_echo_thread — failure detection and failure_rounds counter
# ---------------------------------------------------------------------------

class TestRunEchoThreadFailureDetection:
    def test_failure_round_increments_when_conn_drops(self):
        """When prev_conn is valid and process_next_sample returns None,
        handle_write_failure is called with failure_rounds=1."""
        calls = []
        thread, stop = _make_thread()
        thread.handle_write_failure = MagicMock(side_effect=lambda r: calls.append(r) or None)
        thread._db_disabled = False

        # Inlet: one real sample then stop
        inlet = MagicMock()
        inlet.pull_sample.side_effect = [
            (["ECHO|zone_enter|therapist_01|therapist|arms_reach"], 1.0),
            (None, 0.0),  # timeout — loop will check stop_event
        ]

        # process_next_sample drops the conn on first sample
        original_conn = object()
        sample_returns = iter([None])  # first call drops conn

        with patch("capture.echo_handler.runtime.process_next_sample") as mock_pns:
            mock_pns.side_effect = lambda t, i, c: next(sample_returns, None)

            # Stop after handle_write_failure is called once
            thread.handle_write_failure = MagicMock(side_effect=lambda r: stop.set() or None)

            from capture.echo_handler.runtime import run_echo_thread
            thread.connect_db = MagicMock(return_value=original_conn)
            thread.resolve_inlet = MagicMock(return_value=inlet)
            run_echo_thread(thread)

        thread.handle_write_failure.assert_called_once_with(1)

    def test_successful_retry_resets_failure_rounds(self):
        """If handle_write_failure returns a conn, failure_rounds resets to 0
        and the next failure starts at round 1 again."""
        thread, stop = _make_thread()
        fake_conn = object()
        new_conn = object()

        call_rounds = []
        def track_and_return(r):
            call_rounds.append(r)
            if r == 1:
                return new_conn  # successful retry
            stop.set()
            return None

        thread.handle_write_failure = MagicMock(side_effect=track_and_return)

        conn_sequence = iter([None, None])  # drops conn on first two calls

        with patch("capture.echo_handler.runtime.process_next_sample") as mock_pns:
            mock_pns.side_effect = lambda t, i, c: next(conn_sequence, new_conn)
            thread.connect_db = MagicMock(return_value=fake_conn)
            thread.resolve_inlet = MagicMock(return_value=MagicMock())

            from capture.echo_handler.runtime import run_echo_thread
            run_echo_thread(thread)

        assert call_rounds == [1, 1]  # second failure is round 1 again (counter reset)


# ---------------------------------------------------------------------------
# XDF-only mode
# ---------------------------------------------------------------------------

class TestXDFOnlyMode:
    def test_pull_and_write_xdf_only_writes_marker_not_db(self):
        thread, _ = _make_thread()
        inlet = MagicMock()
        inlet.pull_sample.return_value = (
            ["ECHO|zone_enter|therapist_01|therapist|arms_reach"],
            999.0,
        )

        with patch("capture.echo_handler.runtime.log_event"):
            _pull_and_write_xdf_only(thread, inlet)

        thread._xdf.write_marker.assert_called_once_with(
            "ECHO|zone_enter|therapist_01|therapist|arms_reach",
            999.0,
        )

    def test_pull_and_write_xdf_only_skips_unrecognised_marker(self):
        thread, _ = _make_thread()
        inlet = MagicMock()
        inlet.pull_sample.return_value = (["GARBAGE"], 1.0)

        _pull_and_write_xdf_only(thread, inlet)

        thread._xdf.write_marker.assert_not_called()

    def test_pull_and_write_xdf_only_skips_empty_sample(self):
        thread, _ = _make_thread()
        inlet = MagicMock()
        inlet.pull_sample.return_value = (None, 0.0)

        _pull_and_write_xdf_only(thread, inlet)

        thread._xdf.write_marker.assert_not_called()


# ---------------------------------------------------------------------------
# Existing pipeline tests (unchanged)
# ---------------------------------------------------------------------------

def test_process_next_sample_writes_xdf_before_db_and_logs_marker():
    inlet = MagicMock()
    inlet.pull_sample.return_value = (
        ["ECHO|zone_enter|therapist_01|therapist|arms_reach"],
        123.456,
    )
    thread = MagicMock()
    thread._cfg.session_id = "11111111-1111-1111-1111-111111111111"
    thread._cfg.participant_id = "22222222-2222-2222-2222-222222222222"
    thread._cfg.site_id = "33333333-3333-3333-3333-333333333333"
    thread._cfg.sponsor_id = "44444444-4444-4444-4444-444444444444"
    thread.write_or_buffer.return_value = "conn"

    with patch("capture.echo_handler.runtime.log_event") as log_event:
        returned = process_next_sample(thread, inlet, "conn")

    assert returned == "conn"
    log_event.assert_called_once()
    thread._xdf.write_marker.assert_called_once_with(
        "ECHO|zone_enter|therapist_01|therapist|arms_reach",
        123.456,
    )
    thread.write_or_buffer.assert_called_once()
    row = thread.write_or_buffer.call_args.args[1]
    assert row["event_type"] == "zone_enter"
    assert row["actor_role"] == "therapist"
    assert row["zone_label"] == "arms_reach"
    assert row["lsl_timestamp"] == 123.456


def test_echo_buffer_row_logs_after_append_when_full():
    from capture.echo_handler.writer import BUFFER_MAX, ECHOWriter

    writer = ECHOWriter()
    writer.buffer.extend({"event_type": "zone_enter"} for _ in range(BUFFER_MAX))

    with patch("capture.echo_handler.writer.log.error") as log_error:
        writer.buffer_row({"event_type": "manual_marker"})

    assert len(writer.buffer) == BUFFER_MAX
    assert writer.buffer[-1] == {"event_type": "manual_marker"}
    log_error.assert_called_once()
    extra = log_error.call_args.kwargs["extra"]
    assert extra["buffer_depth"] == BUFFER_MAX
