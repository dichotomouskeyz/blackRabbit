"""LSL publication with explicit mappings and provenance."""

import json
from dataclasses import asdict
from importlib.metadata import version

import numpy as np
import pylsl

from capture.hardware.adapter import BoardBatch, validate_profile_layout
from capture.hardware.clock import EpochClock
from capture.hardware.configuration import DeviceBinding
from capture.hardware.errors import HardwareError


class LSLPublisher:
    def __init__(
        self,
        binding: DeviceBinding,
        clock: EpochClock,
        run_id: str,
        buffer_seconds: float,
    ) -> None:
        self.binding = binding
        self.clock = clock
        self.run_id = run_id
        self.buffer_seconds = buffer_seconds
        self.layouts = validate_profile_layout(binding.profile)
        self.presets = {p.preset: p for p in binding.profile.presets}
        self.outlets: dict[str, pylsl.StreamOutlet] = {}
        self.sample_counts: dict[str, int] = {}

    def open(self) -> None:
        profile = self.binding.profile
        for preset in profile.presets:
            for signal in preset.signals:
                stream_name = f"blackRabbit.{self.binding.source_id}.{signal.id}"
                info = pylsl.StreamInfo(
                    stream_name,
                    signal.signal_type,
                    len(signal.rows),
                    preset.sampling_rate,
                    pylsl.cf_double64,
                    f"{stream_name}.{self.run_id}",
                )
                desc = info.desc()
                channels = desc.append_child("channels")
                for label, unit in zip(signal.labels, signal.units):
                    channel = channels.append_child("channel")
                    channel.append_child_value("label", label)
                    channel.append_child_value("unit", unit)
                    channel.append_child_value("type", signal.signal_type)
                metadata = {
                    "schema_version": 1,
                    "run_id": self.run_id,
                    "source_id": self.binding.source_id,
                    "source_kind": "simulated" if profile.board_id == -1 else "hardware",
                    "profile_id": profile.id,
                    "profile_version": profile.version,
                    "profile_hash": profile.content_hash,
                    "profile": profile.to_dict(),
                    "mapping": asdict(signal),
                    "preset": preset.preset,
                    "brainflow_version": version("brainflow"),
                    "timestamp_origin": preset.timestamp_origin,
                    "timestamp_mapping": {
                        "method": "fixed_epoch_to_lsl_offset",
                        "offset_seconds": self.clock.offset,
                        "measurement_uncertainty_seconds": self.clock.uncertainty,
                        "hardware_latency_verified": False,
                    },
                }
                desc.append_child_value("blackrabbit", json.dumps(metadata, allow_nan=False))
                self.outlets[signal.id] = pylsl.StreamOutlet(
                    info, max_buffered=max(1, int(self.buffer_seconds))
                )
                self.sample_counts[signal.id] = 0

    def publish(self, batch: BoardBatch) -> None:
        if batch.preset not in self.presets:
            raise HardwareError("invalid_batch", "Adapter returned an unconfigured preset")
        layout = self.layouts[batch.preset]
        data = np.asarray(batch.data)
        if data.ndim != 2 or data.shape[0] != layout["num_rows"]:
            raise HardwareError("invalid_batch", "Adapter data shape disagrees with layout")
        if not data.shape[1]:
            return
        timestamps = self.clock.convert(
            f"{self.binding.source_id}:{batch.preset}", data[layout["timestamp_channel"]]
        )
        mapped = []
        for signal in self.presets[batch.preset].signals:
            samples = data[list(signal.rows)].T * signal.scale + signal.offset
            if not np.isfinite(samples).all():
                raise HardwareError("invalid_signal", "Nonfinite source or converted signal value")
            if signal.signal_type == "HRV" and np.any(samples <= 0):
                raise HardwareError("invalid_signal", "Beat intervals must be positive")
            mapped.append((signal, samples))
        # Validate the entire preset chunk before publishing any mapped signal.
        for signal, samples in mapped:
            for sample, timestamp in zip(samples, timestamps):
                self.outlets[signal.id].push_sample(sample.tolist(), float(timestamp))
            self.sample_counts[signal.id] += len(samples)

    def close(self) -> None:
        # pylsl destroys the native outlet when its last Python reference is released.
        self.outlets.clear()
