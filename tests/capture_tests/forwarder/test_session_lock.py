"""Forwarder release ownership contract R-021, R-024 and R-026."""

from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from capture.forwarder import runtime
from capture.forwarder.models import SessionConfig
from capture.session_lock import SessionBusyError, acquire_session_lock


@pytest.fixture
def cfg():
    return SessionConfig(
        **{key: str(uuid4()) for key in ("session_id", "participant_id", "site_id", "sponsor_id")}
    )


def test_lock_denial_uses_bound_session_key_and_fails_fast():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (False,)
    with pytest.raises(SessionBusyError):
        acquire_session_lock(conn, "same-recording")
    cur.execute.assert_called_once_with(
        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", ("same-recording",)
    )
    conn.commit.assert_not_called()


def test_prepare_locks_before_preflight_and_holds_connection_until_stop(cfg, monkeypatch):
    conn = MagicMock()
    sequence = []
    monkeypatch.setattr(runtime.psycopg2, "connect", Mock(return_value=conn))
    monkeypatch.setattr(
        runtime, "acquire_session_lock", lambda c, sid: sequence.append(("lock", c, sid))
    )
    monkeypatch.setattr(
        runtime, "verify_session_ready", lambda c, db: sequence.append(("verify", db, c.session_id))
    )
    monkeypatch.setattr(runtime, "load_session_config", Mock(return_value=cfg))
    monkeypatch.setattr(runtime, "clear_stop_request", Mock())
    engine = runtime.ForwarderEngine(cfg)
    engine.prepare()
    assert sequence == [("lock", conn, cfg.session_id), ("verify", conn, cfg.session_id)]
    runtime.load_session_config.assert_called_once_with(cfg, conn)
    assert engine.session_conn is conn
    conn.close.assert_not_called()
    engine.stop()
    conn.close.assert_called_once()
    assert engine.session_conn is None


def test_busy_capture_releases_rejected_connection_before_start(cfg, monkeypatch):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
    monkeypatch.setattr(runtime.psycopg2, "connect", Mock(return_value=conn))
    preflight = Mock()
    writer = Mock()
    monkeypatch.setattr(runtime, "verify_session_ready", preflight)
    monkeypatch.setattr(runtime, "XDFWriter", writer)
    with pytest.raises(SessionBusyError):
        runtime.run_forwarder(cfg)
    preflight.assert_not_called()
    writer.assert_not_called()
    conn.close.assert_called_once()


@pytest.mark.parametrize("failed_step", ["verify_session_ready", "load_session_config"])
def test_preparation_error_releases_owner_without_starting_capture(cfg, monkeypatch, failed_step):
    conn = MagicMock()
    monkeypatch.setattr(runtime.psycopg2, "connect", Mock(return_value=conn))
    monkeypatch.setattr(runtime, "acquire_session_lock", Mock())
    monkeypatch.setattr(runtime, "verify_session_ready", Mock())
    monkeypatch.setattr(runtime, "load_session_config", Mock(return_value=cfg))
    monkeypatch.setattr(runtime, failed_step, Mock(side_effect=RuntimeError("preflight rejected")))
    writer = Mock()
    monkeypatch.setattr(runtime, "XDFWriter", writer)
    with pytest.raises(RuntimeError, match="preflight rejected"):
        runtime.run_forwarder(cfg)
    writer.assert_not_called()
    conn.close.assert_called_once()


def test_xdf_cleanup_error_still_releases_capture_owner(cfg):
    engine = runtime.ForwarderEngine(cfg)
    conn = MagicMock()
    engine.session_conn = conn
    engine.xdf = Mock()
    engine.xdf.close.side_effect = RuntimeError("flush failed")
    with pytest.raises(RuntimeError, match="flush failed"):
        engine.stop()
    conn.close.assert_called_once()
    assert engine.session_conn is None
