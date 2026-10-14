"""Forwarder release integrity rules R-021..R-026."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from capture.echo_handler.thread import ECHOThread
from capture.forwarder.stream_thread.stream_runtime import run_stream_thread
from capture.xdf.writer import XDFWriteError


@pytest.mark.parametrize("failure", ["inlet", "database", "value"])
def test_required_worker_failure_stops_capture(failure):
    stop = threading.Event()
    inlet = Mock()
    inlet.pull_chunk.side_effect = ValueError("invalid channel shape")
    thread = SimpleNamespace(
        stream_type="EEG",
        stop_event=stop,
        inlet=None,
        conn=None,
        resolve_inlet=lambda: None if failure == "inlet" else inlet,
        connect_db=lambda: None,
        buffer=[],
        sample_index=0,
        chunk_size=1,
        maybe_record_drift=lambda: None,
        flush_buffer=lambda: None,
        set_fatal_error=Mock(),
    )
    if failure == "value":
        thread.connect_db = lambda: setattr(thread, "conn", Mock())
    run_stream_thread(thread)
    assert stop.is_set()
    thread.set_fatal_error.assert_called_once()
    assert isinstance(thread.set_fatal_error.call_args.args[0], Exception)


def test_marker_xdf_failure_stops_shared_capture(monkeypatch):
    stop = threading.Event()
    thread = ECHOThread(SimpleNamespace(), stop, Mock())
    monkeypatch.setattr(thread, "_run", Mock(side_effect=XDFWriteError("disk full")))
    thread.run()
    assert stop.is_set()
    assert isinstance(thread.fatal_error, XDFWriteError)


def test_canonical_identity_mismatch_fails_before_metadata_reads():
    from capture.forwarder.preflight import SessionIdentityError, verify_session_ready

    cfg = SimpleNamespace(
        session_id="session", sponsor_id="sponsor", participant_id="p", site_id="s"
    )
    conn = Mock()
    cur = Mock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    conn.cursor.return_value = cur
    cur.fetchone.return_value = ("active", "another-person", "s")
    with pytest.raises(SessionIdentityError):
        verify_session_ready(cfg, conn)
    assert cur.execute.call_count == 1
