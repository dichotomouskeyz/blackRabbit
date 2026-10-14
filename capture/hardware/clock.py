"""Explicit epoch-to-LSL conversion; no hardware latency claim."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from capture.hardware.errors import HardwareError


@dataclass
class EpochClock:
    offset: float
    uncertainty: float
    max_jump: float
    local_clock: Callable[[], float]
    wall_clock: Callable[[], float] = time.time
    _last: dict[str, float] = field(default_factory=dict)

    @classmethod
    def measure(cls, local_clock, max_jump: float, wall_clock=time.time) -> "EpochClock":
        measurements = []
        for _ in range(5):
            before = local_clock()
            epoch = wall_clock()
            after = local_clock()
            if not all(math.isfinite(v) for v in (before, epoch, after)) or after < before:
                raise HardwareError("invalid_clock", "Cannot measure the local clock")
            measurements.append(((after - before) / 2, (before + after) / 2 - epoch))
        uncertainty, offset = min(measurements)
        return cls(offset, uncertainty, max_jump, local_clock, wall_clock)

    def check(self) -> None:
        before = self.local_clock()
        epoch = self.wall_clock()
        after = self.local_clock()
        values = (before, epoch, after)
        if not all(math.isfinite(v) for v in values) or after < before:
            raise HardwareError("invalid_clock", "Invalid host clock measurement")
        error = abs((before + after) / 2 - epoch - self.offset)
        if error > self.max_jump + (after - before) / 2 + self.uncertainty:
            raise HardwareError("clock_discontinuity", "Host clock offset changed beyond tolerance")

    def convert(self, key: str, timestamps: np.ndarray) -> np.ndarray:
        ts = np.asarray(timestamps, dtype=np.float64)
        if ts.ndim != 1 or not ts.size:
            raise HardwareError("invalid_timestamp", "Expected nonempty timestamp vector")
        if not np.isfinite(ts).all() or np.any(ts <= 0) or np.any(np.diff(ts) <= 0):
            raise HardwareError(
                "invalid_timestamp", "Source timestamps must be finite and increasing"
            )
        if key in self._last and ts[0] <= self._last[key]:
            raise HardwareError("invalid_timestamp", "Source timestamp moved backward or repeated")
        converted = ts + self.offset
        if not np.isfinite(converted).all() or np.any(converted == 0):
            # LSL treats zero as "timestamp now", which would silently change source timing.
            raise HardwareError("invalid_timestamp", "Converted timestamp is not publishable")
        self._last[key] = float(ts[-1])
        return converted
