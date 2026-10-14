"""HW-007..010: opt in with pytest -m lsl_smoke (no physical hardware)."""

import json
import threading
import time
import uuid
from dataclasses import replace

import numpy as np
import pytest


@pytest.mark.lsl_smoke
def test_native_multiple_presets(request):
    if request.config.getoption("markexpr") != "lsl_smoke":
        pytest.skip("Select explicitly with -m lsl_smoke")

    from capture.hardware.configuration import BridgeConfig, DeviceBinding
    from capture.hardware.profiles import PresetProfile, SignalProfile, synthetic_profile
    from capture.hardware.runtime import run_bridge

    profile = synthetic_profile()
    auxiliary = PresetProfile(
        1,
        250,
        "simulated",
        (SignalProfile("aux-eda", "EDA", (8,), ("aux-eda",), ("unknown",), ("unknown",)),),
    )
    profile = replace(profile, presets=(*profile.presets, auxiliary))
    result = run_bridge(BridgeConfig((DeviceBinding("native-presets", profile),)), duration_s=0.2)
    counts = result["samples_published"]["native-presets"]
    assert counts["eeg"] > 0
    assert counts["aux-eda"] > 0


@pytest.mark.lsl_smoke
def test_native_two_devices_and_explicit_restart(request):
    if request.config.getoption("markexpr") != "lsl_smoke":
        pytest.skip("Select explicitly with -m lsl_smoke")

    from capture.hardware.configuration import BridgeConfig, DeviceBinding
    from capture.hardware.profiles import synthetic_profile
    from capture.hardware.runtime import run_bridge

    config = BridgeConfig(
        tuple(DeviceBinding(f"native-{name}", synthetic_profile()) for name in ("left", "right"))
    )
    runs = [run_bridge(config, duration_s=0.15), run_bridge(config, duration_s=0.15)]
    assert runs[0]["run_id"] != runs[1]["run_id"]
    for run in runs:
        assert run["state"] == "stopped"
        assert set(run["samples_published"]) == {"native-left", "native-right"}
        assert all(
            count > 0 for signals in run["samples_published"].values() for count in signals.values()
        )


@pytest.mark.lsl_smoke
def test_native_brainflow_to_lsl(request):
    if request.config.getoption("markexpr") != "lsl_smoke":
        pytest.skip("Select explicitly with -m lsl_smoke")

    import pylsl

    from capture.hardware.configuration import BridgeConfig, DeviceBinding
    from capture.hardware.profiles import synthetic_profile
    from capture.hardware.publisher import LSLPublisher
    from capture.hardware.runtime import run_bridge

    source = f"smoke-{uuid.uuid4().hex[:10]}"
    config = BridgeConfig((DeviceBinding(source, synthetic_profile()),))
    stop = threading.Event()
    expected = {}
    errors = []
    results = []

    class ObservedPublisher(LSLPublisher):
        def publish(self, batch):
            for index, ts in enumerate(batch.data[30]):
                expected[round(float(ts + self.clock.offset), 6)] = batch.data[1:17, index].copy()
            super().publish(batch)

    def run():
        try:
            results.append(
                run_bridge(
                    config, stop_event=stop, duration_s=8, publisher_factory=ObservedPublisher
                )
            )
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    inlet = None
    try:
        streams = pylsl.resolve_byprop("name", f"blackRabbit.{source}.eeg", timeout=4)
        assert streams, f"No native outlet; errors: {errors}"
        inlet = pylsl.StreamInlet(streams[0], processing_flags=pylsl.proc_none)
        info = inlet.info(timeout=2)
        assert info.channel_count() == 16
        assert info.nominal_srate() == 250
        metadata = json.loads(info.desc().child_value("blackrabbit"))
        assert metadata["profile_hash"] == synthetic_profile().content_hash
        assert metadata["source_kind"] == "simulated"
        samples, timestamps = [], []
        deadline = time.monotonic() + 3
        while len(samples) < 30 and time.monotonic() < deadline:
            chunk, times = inlet.pull_chunk(timeout=0.2)
            samples.extend(chunk)
            timestamps.extend(times)
        assert len(samples) >= 30
        assert np.all(np.diff(timestamps) > 0)
        assert abs(pylsl.local_clock() - timestamps[-1]) < 2
        for sample, timestamp in zip(samples, timestamps):
            np.testing.assert_allclose(sample, expected[round(timestamp, 6)], rtol=0, atol=1e-10)
    finally:
        if inlet is not None:
            inlet.close_stream()
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
    assert not errors
    assert results[0]["state"] == "cancelled"
    assert results[0]["samples_published"][source]["ppg"] >= 30
