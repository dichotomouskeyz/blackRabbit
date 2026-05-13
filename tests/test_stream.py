"""Tests for capture.lsl_simulator.

Verifies signal handling, stream metadata, per-stream sample correctness,
and stop-event behaviour. pylsl is patched throughout — no real LSL network
required.

Structure:
  TestSimulatorSignal   — _handle_stop, SIGTERM wiring
  TestSimulatorEEG      — stream info, sample shape, physiological range
  TestSimulatorHRV      — stream info, physiological range, stop behaviour
  TestSimulatorEDA      — stream info, non-negative clamping, stop behaviour
  TestSimulatorResp     — stream info, waveform range, stop behaviour
"""

import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

import capture.lsl_simulator as sim


@pytest.fixture(autouse=True)
def reset_stop():
    """Reset the module-level stop event before and after every test."""
    sim._stop.clear()
    yield
    sim._stop.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_samples(target, n: int = 5, timeout_s: float = 5.0) -> list:
    """Run target() in a daemon thread; stop after n samples are pushed.

    time.sleep inside the simulator module is patched to a no-op so the
    loop runs at full CPU speed. A threading.Event signals completion so the
    test doesn't depend on wall-clock sleep.
    """
    samples: list = []
    done = threading.Event()

    outlet = MagicMock()

    def _on_push(s):
        samples.append(list(s))
        if len(samples) >= n:
            sim._stop.set()
            done.set()

    outlet.push_sample.side_effect = _on_push

    with (
        patch("capture.lsl_simulator.pylsl.StreamInfo"),
        patch("capture.lsl_simulator.pylsl.StreamOutlet", return_value=outlet),
        patch("capture.lsl_simulator.time.sleep"),
    ):
        t = threading.Thread(target=target, daemon=True)
        t.start()
        done.wait(timeout=timeout_s)
        sim._stop.set()
        t.join(timeout=2.0)

    return samples


def _stream_info_kwargs(target) -> dict:
    """Return the keyword args that target() passed to pylsl.StreamInfo."""
    with (
        patch("capture.lsl_simulator.pylsl.StreamInfo") as mock_info,
        patch("capture.lsl_simulator.pylsl.StreamOutlet"),
    ):
        sim._stop.set()  # exit immediately after stream setup
        target()
    return mock_info.call_args.kwargs


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


class TestSimulatorSignal:

    def test_stop_event_starts_clear(self):
        """Module-level _stop is clear before each test (fixture resets it)."""
        assert not sim._stop.is_set()

    def test_handle_stop_sets_stop_event(self):
        """Calling _handle_stop directly sets _stop regardless of signum."""
        sim._handle_stop(signal.SIGTERM, None)
        assert sim._stop.is_set()

    def test_handle_stop_accepts_sigint(self):
        """_handle_stop works for SIGINT — same handler is registered for both."""
        sim._handle_stop(signal.SIGINT, None)
        assert sim._stop.is_set()

    def test_sigterm_registered_fires_stop(self):
        """The registered SIGTERM handler sets _stop without terminating pytest."""
        old = signal.getsignal(signal.SIGTERM)
        try:
            signal.signal(signal.SIGTERM, sim._handle_stop)
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)
            assert sim._stop.is_set()
        finally:
            signal.signal(signal.SIGTERM, old)


# ---------------------------------------------------------------------------
# EEG stream
# ---------------------------------------------------------------------------


class TestSimulatorEEG:

    def test_stream_info_name_from_settings(self):
        """StreamInfo is created with name = settings.LSL_STREAM_EEG."""
        kwargs = _stream_info_kwargs(sim._run_eeg)
        assert kwargs["name"] == sim.settings.LSL_STREAM_EEG

    def test_stream_info_channel_count_from_settings(self):
        """StreamInfo channel_count matches settings.EEG_CHANNEL_COUNT."""
        kwargs = _stream_info_kwargs(sim._run_eeg)
        assert kwargs["channel_count"] == sim.settings.EEG_CHANNEL_COUNT

    def test_eeg_exits_on_stop_event(self):
        """_run_eeg exits within 1 second when _stop is set before start."""
        with (
            patch("capture.lsl_simulator.pylsl.StreamInfo"),
            patch("capture.lsl_simulator.pylsl.StreamOutlet"),
            patch("capture.lsl_simulator.time.sleep"),
        ):
            sim._stop.set()
            t = threading.Thread(target=sim._run_eeg, daemon=True)
            t.start()
            t.join(timeout=1.0)
        assert not t.is_alive()

    def test_eeg_sample_length_equals_channel_count(self):
        """Each EEG sample has exactly EEG_CHANNEL_COUNT values."""
        samples = _collect_samples(sim._run_eeg)
        assert len(samples) > 0
        for s in samples:
            assert len(s) == sim.settings.EEG_CHANNEL_COUNT

    def test_eeg_sample_values_in_physiological_range(self):
        """EEG values stay within ±500 µV (covers all five bands plus noise floor)."""
        samples = _collect_samples(sim._run_eeg)
        assert len(samples) > 0
        for s in samples:
            for v in s:
                assert (
                    -500.0 < v < 500.0
                ), f"EEG value {v} µV outside physiological range"


# ---------------------------------------------------------------------------
# HRV stream
# ---------------------------------------------------------------------------


class TestSimulatorHRV:

    def test_stream_info_name_from_settings(self):
        """StreamInfo is created with name = settings.LSL_STREAM_HRV."""
        kwargs = _stream_info_kwargs(sim._run_hrv)
        assert kwargs["name"] == sim.settings.LSL_STREAM_HRV

    def test_hrv_exits_on_stop_event(self):
        """_run_hrv exits within 1 second when _stop is set before start."""
        with (
            patch("capture.lsl_simulator.pylsl.StreamInfo"),
            patch("capture.lsl_simulator.pylsl.StreamOutlet"),
            patch("capture.lsl_simulator.time.sleep"),
        ):
            sim._stop.set()
            t = threading.Thread(target=sim._run_hrv, daemon=True)
            t.start()
            t.join(timeout=1.0)
        assert not t.is_alive()

    def test_hrv_rr_interval_within_physiological_bounds(self):
        """All RR intervals stay within the physiological clamp (400–1400 ms)."""
        samples = _collect_samples(sim._run_hrv)
        assert len(samples) > 0
        for s in samples:
            assert 400.0 <= s[0] <= 1400.0, f"RR interval {s[0]} ms outside bounds"

    def test_hrv_single_channel(self):
        """Each HRV sample has exactly one value (RR interval in ms)."""
        samples = _collect_samples(sim._run_hrv)
        assert len(samples) > 0
        for s in samples:
            assert len(s) == 1


# ---------------------------------------------------------------------------
# EDA stream
# ---------------------------------------------------------------------------


class TestSimulatorEDA:

    def test_stream_info_name_from_settings(self):
        """StreamInfo is created with name = settings.LSL_STREAM_EDA."""
        kwargs = _stream_info_kwargs(sim._run_eda)
        assert kwargs["name"] == sim.settings.LSL_STREAM_EDA

    def test_eda_exits_on_stop_event(self):
        """_run_eda exits within 1 second when _stop is set before start."""
        with (
            patch("capture.lsl_simulator.pylsl.StreamInfo"),
            patch("capture.lsl_simulator.pylsl.StreamOutlet"),
            patch("capture.lsl_simulator.time.sleep"),
        ):
            sim._stop.set()
            t = threading.Thread(target=sim._run_eda, daemon=True)
            t.start()
            t.join(timeout=1.0)
        assert not t.is_alive()

    def test_eda_conductance_is_non_negative(self):
        """EDA values are always ≥ 0 (clamped by max(0.0, val) in the generator)."""
        samples = _collect_samples(sim._run_eda)
        assert len(samples) > 0
        for s in samples:
            assert s[0] >= 0.0, f"EDA conductance {s[0]} µS is negative"

    def test_eda_single_channel(self):
        """Each EDA sample has exactly one value (conductance in µS)."""
        samples = _collect_samples(sim._run_eda)
        assert len(samples) > 0
        for s in samples:
            assert len(s) == 1


# ---------------------------------------------------------------------------
# Respiration stream
# ---------------------------------------------------------------------------


class TestSimulatorRespiration:

    def test_stream_info_name_from_settings(self):
        """StreamInfo is created with name = settings.LSL_STREAM_RESPIRATION."""
        kwargs = _stream_info_kwargs(sim._run_respiration)
        assert kwargs["name"] == sim.settings.LSL_STREAM_RESPIRATION

    def test_respiration_exits_on_stop_event(self):
        """_run_respiration exits within 1 second when _stop is set before start."""
        with (
            patch("capture.lsl_simulator.pylsl.StreamInfo"),
            patch("capture.lsl_simulator.pylsl.StreamOutlet"),
            patch("capture.lsl_simulator.time.sleep"),
        ):
            sim._stop.set()
            t = threading.Thread(target=sim._run_respiration, daemon=True)
            t.start()
            t.join(timeout=1.0)
        assert not t.is_alive()

    def test_respiration_values_within_waveform_range(self):
        """Respiration values stay within [-2, 2] (asymmetric sine ±1 plus small noise)."""
        samples = _collect_samples(sim._run_respiration)
        assert len(samples) > 0
        for s in samples:
            assert -2.0 < s[0] < 2.0, f"Respiration value {s[0]} outside expected range"

    def test_respiration_single_channel(self):
        """Each respiration sample has exactly one value (normalized waveform)."""
        samples = _collect_samples(sim._run_respiration)
        assert len(samples) > 0
        for s in samples:
            assert len(s) == 1
