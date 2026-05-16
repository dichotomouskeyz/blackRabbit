"""_StreamThread unit tests — no DB, no thread start."""

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import psycopg2

from capture.forwarder import (
    BUFFER_MAX_CHUNKS,
    SessionConfig,
    _EEG_INSERT,
    _StreamThread,
    _build_eeg_rows,
)

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
) -> _StreamThread:
    if stop_event is None:
        stop_event = threading.Event()
    if xdf_writer is None:
        xdf_writer = MagicMock()
    return _StreamThread(
        stream_name=f"Test{stream_type}",
        stream_type=stream_type,
        chunk_size=25,
        row_builder=_build_eeg_rows,
        insert_sql=_EEG_INSERT,
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
        assert t._sample_index == 0

    def test_initial_buffer_is_empty(self):
        t = _make_thread()
        assert len(t._buffer) == 0

    def test_write_rows_returns_conn_on_success(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch("psycopg2.extras.execute_batch"):
            result = t._write_rows(mock_conn, rows)

        assert result is mock_conn
        mock_conn.commit.assert_called_once()

    def test_write_rows_buffers_on_operational_error(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch(
            "psycopg2.extras.execute_batch",
            side_effect=psycopg2.OperationalError("lost connection"),
        ):
            result = t._write_rows(mock_conn, rows)

        assert result is None
        assert len(t._buffer) == 1
        assert t._buffer[0] is rows
        mock_conn.close.assert_called_once()

    def test_write_rows_rolls_back_on_non_connection_error(self):
        t = _make_thread()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = MagicMock()

        rows = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        with patch(
            "psycopg2.extras.execute_batch",
            side_effect=psycopg2.IntegrityError("duplicate key"),
        ):
            result = t._write_rows(mock_conn, rows)

        assert result is mock_conn
        mock_conn.rollback.assert_called_once()

    def test_flush_buffer_drains_all_chunks(self):
        t = _make_thread()
        rows_a = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        rows_b = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.004, 1)
        t._buffer.append(rows_a)
        t._buffer.append(rows_b)

        mock_conn = MagicMock()
        t._write_rows = lambda conn, rows: conn

        result = t._flush_buffer(mock_conn)

        assert len(t._buffer) == 0
        assert result is mock_conn

    def test_flush_buffer_stops_on_connection_drop(self):
        t = _make_thread()
        rows_a = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.0, 0)
        rows_b = _build_eeg_rows(_EEG_SAMPLE, _CFG, 1000.004, 1)
        t._buffer.append(rows_a)
        t._buffer.append(rows_b)

        mock_conn = MagicMock()
        t._write_rows = lambda conn, rows: None

        result = t._flush_buffer(mock_conn)

        assert result is None
        assert len(t._buffer) == 2

    def test_buffer_max_chunks_constant_is_positive(self):
        assert BUFFER_MAX_CHUNKS > 0
