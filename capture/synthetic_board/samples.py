"""Synthetic APEX biosignal sample generators."""

import math
import random


def eeg_sample(index: int, channel_count: int, rate_hz: float) -> list[float]:
    t = index / rate_hz
    return [
        25.0 * math.sin(2.0 * math.pi * (8.0 + ch * 0.35) * t)
        + 6.0 * math.sin(2.0 * math.pi * 1.2 * t)
        + random.uniform(-2.0, 2.0)  # nosec B311
        for ch in range(channel_count)
    ]


def hrv_sample(index: int, rate_hz: float) -> list[float]:
    t = index / rate_hz
    rr_ms = 860.0 + 45.0 * math.sin(2.0 * math.pi * 0.1 * t)
    return [rr_ms + random.uniform(-8.0, 8.0)]  # nosec B311


def eda_sample(index: int, rate_hz: float) -> list[float]:
    t = index / rate_hz
    conductance = 3.5 + 0.35 * math.sin(2.0 * math.pi * 0.03 * t)
    return [max(0.05, conductance + random.uniform(-0.04, 0.04))]  # nosec B311


def respiration_sample(index: int, rate_hz: float) -> list[float]:
    t = index / rate_hz
    amplitude = math.sin(2.0 * math.pi * 0.25 * t)
    return [amplitude + random.uniform(-0.03, 0.03)]  # nosec B311
