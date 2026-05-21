"""Unit tests for ECHO ingestion pipeline logging and DB write behavior."""

from unittest.mock import MagicMock, patch

import capture.echo_handler.db as db
from capture.echo_handler.runtime import process_next_sample


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
    message, = info.call_args.args
    assert message == "ECHO event persisted"
    extra = info.call_args.kwargs["extra"]
    assert extra["session_id"] == row["session_id"]
    assert extra["event_type"] == "zone_enter"
    assert extra["actor_role"] == "therapist"
    assert extra["zone_label"] == "arms_reach"
    assert extra["lsl_timestamp"] == 123.456
    assert extra["ingestion_path"] == "live_db"


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
