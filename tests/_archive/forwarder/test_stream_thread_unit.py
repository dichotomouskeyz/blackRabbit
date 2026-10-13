"""StreamThread unit tests — no DB, no thread start."""

import threading
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from capture.forwarder.models import BUFFER_MAX_CHUNKS, SessionConfig
from capture.forwarder.rows import build_eeg_rows
from capture.forwarder.sql import EEG_INSERT
from capture.forwarder.stream_thread.stream_chunks import buffer_chunk, process_chunk
from capture.forwarder.stream_thread.stream_thread import StreamThread

_SESSION = "f1d00008-0000-4444-aaaa-000000000001"
_PART = "f1d00008-0000-4444-bbbb-000000000001"
_SITE = "f1d00008-0000-4444-cccc-000000000001"
_SPONSOR = "f1d00008-0000-4444-dddd-000000000001"

_CFG = SessionConfig(
    session_id=_SESSION,
    participant_id=_PART,
    site_id=_SITE,
    sponsor_id=_SPONSOR,
)

_EEG_SAMPLE = [0.1, 0.2, 0.3, 0.4, -0.1, -0.2, -0.3, -0.4]


def _make_thread(
    stop_event: threading.Event | None = None,
    xdf_writer=None,
    stream_type: str = "EEG",
    cfg: SessionConfig = _CFG,
) -> StreamThread:
    if stop_event is None:
        stop_event = threading.Event()
    if xdf_writer is None:
        xdf_writer = MagicMock()
    return StreamThread(
        stream_name=f"Test{stream_type}",
        stream_type=stream_type,
        chunk_size=25,
        row_builder=build_eeg_rows,
        insert_sql=EEG_INSERT,
        cfg=cfg,
        stop_event=stop_event,
        xdf_writer=xdf_writer,
        table_name="eeg_samples",
        hash_fields=("sample_index", "channel_id", "voltage"),
        hash_sort_keys=("sample_index", "channel_id"),
    )


class TestStreamThreadUnit:
    def test_thread_name_reflects_stream_type(self):
        t = _make_thread(stream_type="HRV")
        assert t.name == "fwd_hrv"

    def test_thread_is_daemon(self):
        t = _make_thread()
        assert t.daemon is True

    def test_initial_sample_index_is_zero(self):
        t = _make_thread()
        assert t.sample_index == 0

    def test_initial_buffer_is_empty(self):
        t = _make_thread()
        assert len(t.buffer) == 0

    def test_write_rows_returns_conn_on_success(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        rows = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch("psycopg2.extras.execute_batch"):
            result = t.write_rows(mock_conn, rows)

        assert result is mock_conn
        mock_cur.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_write_rows_buffers_on_operational_error(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch(
            "psycopg2.extras.execute_batch",
            side_effect=psycopg2.OperationalError("lost connection"),
        ):
            result = t.write_rows(mock_conn, rows)

        assert result is None
        assert len(t.buffer) == 0
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_write_rows_rolls_back_on_non_connection_error(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch(
            "psycopg2.extras.execute_batch",
            side_effect=psycopg2.IntegrityError("duplicate key"),
        ):
            with pytest.raises(RuntimeError, match="sample chunk and integrity log"):
                t.write_rows(mock_conn, rows)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_write_rows_rolls_back_and_buffers_on_integrity_operational_error(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()
        t.try_reconnect = lambda: None

        with (
            patch("psycopg2.extras.execute_batch"),
            patch(
                "capture.forwarder.stream_thread.stream_db.write_integrity_log",
                side_effect=psycopg2.OperationalError("deadlock detected"),
            ),
        ):
            result = process_chunk(t, mock_conn, [_EEG_SAMPLE], [1000.0])

        assert result is None
        assert len(t.buffer) == 1
        assert len(t.buffer[0]) == 8
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_write_rows_rolls_back_and_raises_on_integrity_db_error(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with (
            patch("psycopg2.extras.execute_batch"),
            patch(
                "capture.forwarder.stream_thread.stream_db.write_integrity_log",
                side_effect=psycopg2.IntegrityError("bad integrity row"),
            ),
        ):
            with pytest.raises(RuntimeError, match="sample chunk and integrity log"):
                t.write_rows(mock_conn, rows)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_flush_buffer_drains_all_chunks(self):
        t = _make_thread()
        rows_a = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        rows_b = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.004, 1)
        t.buffer.append(rows_a)
        t.buffer.append(rows_b)

        mock_conn = MagicMock()
        t.write_rows = lambda conn, rows: conn

        result = t.flush_buffer(mock_conn)

        assert len(t.buffer) == 0
        assert result is mock_conn

    def test_flush_buffer_stops_on_connection_drop(self):
        t = _make_thread()
        rows_a = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        rows_b = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.004, 1)
        t.buffer.append(rows_a)
        t.buffer.append(rows_b)

        mock_conn = MagicMock()
        t.write_rows = lambda conn, rows: None

        result = t.flush_buffer(mock_conn)

        assert result is None
        assert len(t.buffer) == 2

    def test_buffer_max_chunks_constant_is_positive(self):
        assert BUFFER_MAX_CHUNKS > 0

    def test_buffer_chunk_logs_after_appending_when_full(self):
        t = _make_thread()
        t.buffer.extend([[{"row": i}]] for i in range(BUFFER_MAX_CHUNKS))

        with patch("capture.forwarder.stream_thread.stream_chunks.log.error") as log_error:
            buffer_chunk(t, [{"row": "new"}])

        assert len(t.buffer) == BUFFER_MAX_CHUNKS
        assert t.buffer[-1] == [{"row": "new"}]
        log_error.assert_called_once()
        extra = log_error.call_args.kwargs["extra"]
        assert extra["dropped_rows"] == 1
        assert extra["buffer_depth"] == BUFFER_MAX_CHUNKS

    def test_maybe_record_drift_requires_db_connection(self, monkeypatch):
        t = _make_thread()
        monkeypatch.setattr(
            "capture.forwarder.stream_thread.stream_drift.time.monotonic",
            lambda: 999.0,
        )

        inlet = MagicMock()

        with pytest.raises(RuntimeError, match="clock_drift_log"):
            t.maybe_record_drift(inlet, None)

        inlet.time_correction.assert_not_called()

    def test_maybe_record_drift_writes_clock_drift_log(self, monkeypatch):
        t = _make_thread()
        monkeypatch.setattr(
            "capture.forwarder.stream_thread.stream_drift.time.monotonic",
            lambda: 999.0,
        )
        monkeypatch.setattr(
            "capture.forwarder.stream_thread.stream_drift.pylsl.local_clock",
            lambda: 1234.5,
        )

        inlet = MagicMock()
        inlet.time_correction.return_value = 0.001
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        t.maybe_record_drift(inlet, mock_conn)

        mock_cur.execute.assert_called_once()
        sql, params = mock_cur.execute.call_args.args
        assert "INSERT INTO clock_drift_log" in sql
        assert params["session_id"] == _SESSION
        assert params["stream_type"] == "EEG"
        assert params["remote_clock_offset_s"] == 0.001
        assert params["lsl_timestamp"] == 1234.5
        mock_conn.commit.assert_called_once()

    def test_maybe_record_drift_rolls_back_and_raises_on_db_failure(self, monkeypatch):
        t = _make_thread()
        monkeypatch.setattr(
            "capture.forwarder.stream_thread.stream_drift.time.monotonic",
            lambda: 999.0,
        )

        inlet = MagicMock()
        inlet.time_correction.return_value = 0.001
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.execute.side_effect = psycopg2.DatabaseError("write failed")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with pytest.raises(RuntimeError, match="clock_drift_log"):
            t.maybe_record_drift(inlet, mock_conn)

        mock_conn.rollback.assert_called_once()

    def test_write_integrity_log_records_hash_method(self):
        t = _make_thread()
        rows = build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        mock_cur = MagicMock()

        t.write_integrity_log(mock_cur, rows)

        mock_cur.execute.assert_called_once()
        sql, params = mock_cur.execute.call_args.args
        assert "log_type" in sql
        assert "hash_method" in sql
        assert params[4] == "chunk_integrity"
        assert params[-1] == "md5"
