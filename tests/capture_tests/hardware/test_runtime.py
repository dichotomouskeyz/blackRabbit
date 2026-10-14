"""HW-009..011: bounded acquisition and complete teardown on every exit."""

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from capture.hardware.adapter import BoardBatch, BrainFlowAdapter
from capture.hardware.configuration import BridgeConfig, DeviceBinding
from capture.hardware.errors import HardwareError
from capture.hardware.profiles import synthetic_profile
from capture.hardware.runtime import run_bridge
from config import settings


def _configuration():
    return BridgeConfig(tuple(DeviceBinding(s, synthetic_profile()) for s in ("left", "right")))


def _factories(failure=None):
    events = []

    class FakeAdapter:
        def __init__(self, binding, _buffer):
            self.source = binding.source_id
            events.append((self.source, "created"))

        def _call(self, phase):
            events.append((self.source, phase))
            if failure == (self.source, phase):
                raise RuntimeError("injected failure")

        def prepare(self):
            self._call("prepare")

        def start(self):
            self._call("start")

        def stop(self):
            self._call("stop")

        def release(self):
            self._call("release")

        def read(self):
            self._call("read")
            return [BoardBatch(0, np.ones((32, 1)))]

    class FakePublisher:
        def __init__(self, binding, *_args):
            self.source = binding.source_id
            self.sample_counts = {"eeg": 0, "eda": 0, "ppg": 0}

        def open(self):
            events.append((self.source, "open"))
            if failure == (self.source, "open"):
                raise RuntimeError("injected outlet failure")

        def publish(self, _batch):
            for key in self.sample_counts:
                self.sample_counts[key] += 1

        def close(self):
            events.append((self.source, "close"))

    return FakeAdapter, FakePublisher, events


@pytest.mark.parametrize("phase", ["prepare", "start", "read", "open"])
def test_partial_failures_release_every_created_resource(phase):
    adapter, publisher, events = _factories(("right", phase))
    with pytest.raises(HardwareError):
        run_bridge(
            _configuration(), duration_s=0.02, adapter_factory=adapter, publisher_factory=publisher
        )
    for source in ("left", "right"):
        assert (source, "stop") in events
        assert (source, "release") in events
        if (source, "open") in events:
            assert (source, "close") in events


def test_multiple_sources_publish_and_finish_cleanly(monkeypatch):
    monkeypatch.setattr(settings, "HARDWARE_POLL_SECONDS", 0.001)
    adapter, publisher, events = _factories()
    notifications = []
    result = run_bridge(
        _configuration(),
        duration_s=0.02,
        on_event=notifications.append,
        adapter_factory=adapter,
        publisher_factory=publisher,
    )
    assert result["state"] == "stopped"
    assert all(
        count > 0 for values in result["samples_published"].values() for count in values.values()
    )
    assert [e["event"] for e in notifications] == ["preparing", "streaming", "stopped"]
    for source in ("left", "right"):
        assert events.index((source, "stop")) < events.index((source, "release"))


def test_cancellation_after_prepare_never_starts_and_still_releases():
    adapter, publisher, events = _factories()
    stop = threading.Event()

    class CancelAdapter(adapter):
        def prepare(self):
            super().prepare()
            stop.set()

    result = run_bridge(
        _configuration(),
        stop_event=stop,
        adapter_factory=CancelAdapter,
        publisher_factory=publisher,
    )
    assert result["state"] == "cancelled"
    assert ("left", "release") in events
    assert not any(phase == "start" for _, phase in events)


def test_cleanup_failure_does_not_skip_sibling_release():
    adapter, publisher, events = _factories(("right", "stop"))
    with pytest.raises(HardwareError) as error:
        run_bridge(
            _configuration(), duration_s=0.001, adapter_factory=adapter, publisher_factory=publisher
        )
    assert error.value.code == "cleanup_failed"
    assert ("right", "release") in events
    assert ("left", "release") in events
    assert ("left", "close") in events


def test_no_data_deadline_is_fatal(monkeypatch):
    monkeypatch.setattr(settings, "HARDWARE_POLL_SECONDS", 0.001)
    monkeypatch.setattr(settings, "HARDWARE_NO_DATA_SECONDS", 0.005)
    adapter, publisher, events = _factories()

    class EmptyAdapter(adapter):
        def read(self):
            return []

    with pytest.raises(HardwareError) as error:
        run_bridge(_configuration(), adapter_factory=EmptyAdapter, publisher_factory=publisher)
    assert error.value.code == "source_timeout"
    assert ("left", "release") in events


def test_adapter_fails_at_native_buffer_capacity():
    adapter = BrainFlowAdapter(DeviceBinding("bench", synthetic_profile()), 1)
    adapter.board = SimpleNamespace(get_board_data_count=lambda preset: 250)
    with pytest.raises(HardwareError) as error:
        adapter.read()
    assert error.value.code == "buffer_capacity_reached"
