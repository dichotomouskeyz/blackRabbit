"""HW-002, HW-007..009: mapping and provenance at the LSL boundary."""

import json
from dataclasses import replace

import numpy as np
import pytest

from capture.hardware import publisher as publisher_module
from capture.hardware.adapter import BoardBatch
from capture.hardware.clock import EpochClock
from capture.hardware.configuration import DeviceBinding
from capture.hardware.errors import HardwareError
from capture.hardware.profiles import synthetic_profile


class _Outlet:
    def __init__(self, info, **kwargs):
        self.info = info
        self.samples = []

    def push_sample(self, sample, timestamp):
        self.samples.append((sample, timestamp))


def _publisher(monkeypatch, profile=None):
    monkeypatch.setattr(publisher_module.pylsl, "StreamOutlet", _Outlet)
    clock = EpochClock.measure(lambda: 100, 0.05, lambda: 1000)
    binding = DeviceBinding("bench", profile or synthetic_profile(), (("serial_port", "PRIVATE"),))
    publisher = publisher_module.LSLPublisher(binding, clock, "run-one", 10)
    publisher.open()
    return publisher


def _batch():
    data = np.arange(64, dtype=float).reshape((32, 2))
    data[30] = [1000, 1000.004]
    return BoardBatch(0, data)


def test_multiple_modalities_keep_source_values_timing_and_metadata(monkeypatch):
    publisher = _publisher(monkeypatch)
    batch = _batch()
    publisher.publish(batch)
    assert set(publisher.outlets) == {"eeg", "eda", "ppg"}
    for signal in publisher.binding.profile.presets[0].signals:
        outlet = publisher.outlets[signal.id]
        np.testing.assert_array_equal(
            [s[0] for s in outlet.samples], batch.data[list(signal.rows)].T
        )
        np.testing.assert_allclose([s[1] for s in outlet.samples], [100, 100.004])
        metadata = json.loads(outlet.info.desc().child_value("blackrabbit"))
        assert metadata["profile_hash"] == publisher.binding.profile.content_hash
        assert metadata["source_kind"] == "simulated"
        assert metadata["timestamp_mapping"]["hardware_latency_verified"] is False
        assert "PRIVATE" not in outlet.info.as_xml()
        assert outlet.info.source_id().endswith(".run-one")
    publisher.close()
    assert publisher.outlets == {}


def test_explicit_conversion_and_raw_ecg_type(monkeypatch):
    profile = synthetic_profile()
    preset = profile.presets[0]
    signal = replace(
        preset.signals[0],
        signal_type="ECG",
        scale=0.001,
        units=("mV",) * 16,
        conversion_reference="uV to mV",
    )
    profile = replace(profile, presets=(replace(preset, signals=(signal,)),))
    publisher = _publisher(monkeypatch, profile)
    publisher.publish(_batch())
    assert publisher.outlets["eeg"].info.type() == "ECG"
    np.testing.assert_allclose(
        publisher.outlets["eeg"].samples[0][0], _batch().data[1:17, 0] * 0.001
    )


@pytest.mark.parametrize("bad", ["shape", "nan", "timestamp"])
def test_invalid_chunk_is_not_partially_published(bad, monkeypatch):
    publisher = _publisher(monkeypatch)
    batch = _batch()
    if bad == "shape":
        batch = BoardBatch(0, batch.data[:10])
    elif bad == "nan":
        batch.data[23, 0] = np.nan
    else:
        batch.data[30, 1] = batch.data[30, 0]
    with pytest.raises(HardwareError):
        publisher.publish(batch)
    assert all(not o.samples for o in publisher.outlets.values())
