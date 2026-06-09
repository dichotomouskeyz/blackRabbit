"""Tests for forwarder runtime shutdown behavior."""

from unittest.mock import ANY, MagicMock, patch

import pytest

from capture.forwarder.models import SessionConfig
from capture.forwarder.runtime import join_threads, raise_if_thread_failed, run_forwarder


def test_join_threads_logs_error_when_thread_does_not_stop():
    thread = MagicMock()
    thread.name = "fwd_echo"
    thread.is_alive.return_value = True

    with patch("capture.forwarder.runtime.log.error") as log_error:
        join_threads([thread], timeout_s=0.01)

    thread.join.assert_called_once_with(timeout=0.01)
    log_error.assert_called_once_with(
        "forwarder thread did not stop after join timeout",
        extra={
            "thread_name": "fwd_echo",
            "join_timeout_s": 0.01,
        },
    )


def test_join_threads_does_not_log_when_thread_stops():
    thread = MagicMock()
    thread.name = "fwd_eeg"
    thread.is_alive.return_value = False

    with patch("capture.forwarder.runtime.log.error") as log_error:
        join_threads([thread], timeout_s=0.01)

    thread.join.assert_called_once_with(timeout=0.01)
    log_error.assert_not_called()


def test_raise_if_thread_failed_raises_on_fatal_stream_error():
    thread = MagicMock()
    thread.name = "fwd_eeg"
    thread.fatal_error = RuntimeError("integrity log failed")

    with pytest.raises(RuntimeError, match="fatal stream thread error"):
        raise_if_thread_failed([thread])


def test_raise_if_thread_failed_ignores_clean_threads():
    thread = MagicMock()
    thread.fatal_error = None

    raise_if_thread_failed([thread])


def test_run_forwarder_closes_xdf_when_join_loop_fails():
    cfg = SessionConfig(
        session_id="11111111-1111-1111-1111-111111111111",
        participant_id="22222222-2222-2222-2222-222222222222",
        site_id="33333333-3333-3333-3333-333333333333",
        sponsor_id="44444444-4444-4444-4444-444444444444",
    )
    xdf = MagicMock()
    thread = MagicMock()
    thread.start.return_value = None

    with (
        patch("capture.forwarder.runtime.clear_stop_request"),
        patch("capture.forwarder.runtime.verify_session_ready"),
        patch(
            "capture.forwarder.runtime.load_session_config",
            return_value=cfg,
        ),
        patch("capture.forwarder.runtime.XDFWriter", return_value=xdf),
        patch("capture.forwarder.runtime.signal.signal"),
        patch("capture.forwarder.runtime.build_stream_threads", return_value=[thread]),
        patch("capture.forwarder.runtime.wait_for_stop"),
        patch(
            "capture.forwarder.runtime.join_threads",
            side_effect=RuntimeError("join failed"),
        ),
    ):
        with pytest.raises(RuntimeError, match="join failed"):
            run_forwarder(cfg)

    xdf.close.assert_called_once()


def test_run_forwarder_loads_session_config_once():
    cfg = SessionConfig(
        session_id="11111111-1111-1111-1111-111111111111",
        participant_id="22222222-2222-2222-2222-222222222222",
        site_id="33333333-3333-3333-3333-333333333333",
        sponsor_id="44444444-4444-4444-4444-444444444444",
    )
    xdf = MagicMock()
    thread = MagicMock()
    thread.start.return_value = None
    loaded_cfg = SessionConfig(
        session_id=cfg.session_id,
        participant_id=cfg.participant_id,
        site_id=cfg.site_id,
        sponsor_id=cfg.sponsor_id,
        eeg_channel_names=("Fp1", "Fp2"),
    )

    with (
        patch("capture.forwarder.runtime.clear_stop_request"),
        patch("capture.forwarder.runtime.verify_session_ready"),
        patch(
            "capture.forwarder.runtime.load_session_config",
            return_value=loaded_cfg,
        ) as load_cfg,
        patch("capture.forwarder.runtime.XDFWriter", return_value=xdf),
        patch("capture.forwarder.runtime.signal.signal"),
        patch(
            "capture.forwarder.runtime.build_stream_threads",
            return_value=[thread],
        ) as build_threads,
        patch("capture.forwarder.runtime.wait_for_stop"),
        patch("capture.forwarder.runtime.join_threads"),
        patch("capture.forwarder.runtime.raise_if_thread_failed"),
    ):
        run_forwarder(cfg)

    load_cfg.assert_called_once_with(cfg)
    build_threads.assert_called_once_with(loaded_cfg, ANY, xdf)
