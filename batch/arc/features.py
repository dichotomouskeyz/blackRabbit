"""Shared epoch features for baseline and ARC responses (arc-batch-release B-003/004)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

import numpy as np

EXTRACTOR_VERSION = "epoch-features-1"
COMPONENTS = {
    "eeg": ("eeg_alpha_power", "eeg_theta_power", "eeg_beta_power"),
    "hrv": ("hrv_rmssd", "hrv_sdnn", "heart_rate_bpm"),
    "eda": ("eda_mean",),
    "respiration": ("respiration_rate", "respiration_amplitude"),
}
BANDS = {
    "eeg_alpha_power": (8.0, 13.0),
    "eeg_theta_power": (4.0, 8.0),
    "eeg_beta_power": (13.0, 30.0),
}


@dataclass(frozen=True)
class Sample:
    timestamp: float
    value: float
    flagged: bool = False
    channel: str = ""
    rate: float | None = None


@dataclass(frozen=True)
class FeatureSeries:
    modality: str
    component: str
    unit: str
    values: tuple[float | None, ...]
    counts: tuple[int, ...]
    origin: float
    epoch_s: float


def band_power(values: list[float], timestamps: list[float], band: tuple[float, float]) -> float:
    """Integrate a demeaned Hann periodogram; return captured voltage units squared."""
    x = np.asarray(values, dtype=float)
    ts = np.asarray(timestamps, dtype=float)
    if len(x) < 8 or not np.all(np.isfinite(x)):
        raise ValueError("EEG requires at least 8 finite samples")
    gaps = np.diff(ts)
    dt = float(np.median(gaps))
    if dt <= 0 or np.max(np.abs(gaps - dt)) > dt * 0.2:
        raise ValueError("EEG samples must be regularly spaced within 20 percent")
    fs = 1.0 / dt
    if fs / 2 < band[1]:
        raise ValueError("EEG sample rate does not cover the configured band")
    window = np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft((x - np.mean(x)) * window)) ** 2
    spectrum /= fs * np.sum(window**2)
    spectrum[1 : -1 if len(x) % 2 == 0 else None] *= 2
    frequencies = np.fft.rfftfreq(len(x), dt)
    mask = (frequencies >= band[0]) & (frequencies < band[1])
    return float(np.sum(spectrum[mask]) * fs / len(x))


def epoch_value(
    modality: str,
    component: str,
    samples: list[Sample],
    *,
    check_budget: Callable[[], None] | None = None,
) -> float | None:
    """Extract one defined feature; never substitute a proxy for missing inputs."""
    if component not in COMPONENTS.get(modality, ()):
        raise ValueError(f"unsupported component: {modality}.{component}")
    if len(samples) < 2:
        return None
    if check_budget is not None:
        check_budget()
    values = np.asarray([sample.value for sample in samples], dtype=float)
    if modality == "eeg":
        channels: dict[str, list[Sample]] = {}
        for index, sample in enumerate(samples):
            if check_budget is not None and index % 4096 == 0:
                check_budget()
            channels.setdefault(sample.channel, []).append(sample)
        powers = []
        for channel in sorted(channels):
            if check_budget is not None:
                check_budget()
            rows = sorted(channels[channel], key=lambda row: row.timestamp)
            try:
                powers.append(
                    band_power(
                        [r.value for r in rows], [r.timestamp for r in rows], BANDS[component]
                    )
                )
            except ValueError:
                return None
        return float(np.mean(powers))
    if component == "hrv_rmssd":
        return float(np.sqrt(np.mean(np.diff(values) ** 2)))
    if component == "hrv_sdnn":
        return float(np.std(values, ddof=1))
    if component == "heart_rate_bpm":
        return float(np.mean(60000.0 / values))
    if component == "respiration_rate":
        rates = [s.rate for s in samples if s.rate is not None and isfinite(s.rate) and s.rate > 0]
        if len(rates) != len(samples):
            return None
        return float(np.mean(rates))
    return float(np.mean(values))


def feature_series(
    modality: str,
    samples: list[Sample],
    components: list[str],
    *,
    origin: float,
    end: float,
    epoch_s: float,
    max_degraded_fraction: float = 0.5,
    amplitude_unit: str = "captured_amplitude_unit",
    expected_channels: tuple[str, ...] = (),
    sample_rate_hz: float | None = None,
    check_budget: Callable[[], None] | None = None,
) -> tuple[FeatureSeries, ...]:
    """Reject degraded/incomplete epochs and extract each configured component once."""
    if check_budget is not None:
        check_budget()
    count = max(0, int(np.floor((end - origin) / epoch_s + 1e-8)))
    buckets: list[list[Sample]] = [[] for _ in range(count)]
    finite_rows = [row for row in samples if isfinite(row.timestamp)]
    if modality == "eeg" and not expected_channels:
        expected_channels = tuple(sorted({row.channel for row in finite_rows}))
    for row_index, row in enumerate(sorted(finite_rows, key=lambda r: (r.timestamp, r.channel))):
        if check_budget is not None and row_index % 4096 == 0:
            check_budget()
        index = int(np.floor((row.timestamp - origin) / epoch_s + 1e-8))
        if 0 <= index < count:
            buckets[index].append(row)
    result = []
    for component in components:
        if check_budget is not None:
            check_budget()
        if component not in COMPONENTS.get(modality, ()):
            raise ValueError(f"unsupported component: {modality}.{component}")
        values, counts = [], []
        for bucket in buckets:
            if check_budget is not None:
                check_budget()
            clean = [
                s
                for s in bucket
                if not s.flagged and isfinite(s.value) and (modality != "hrv" or s.value > 0)
            ]
            degraded = 1.0 - len(clean) / len(bucket) if bucket else 1.0
            value = None
            channel_counts = Counter(row.channel for row in clean) if modality == "eeg" else {}
            channel_coverage = modality != "eeg" or set(expected_channels) == set(channel_counts)
            if sample_rate_hz is not None and sample_rate_hz > 0:
                expected_count = epoch_s * sample_rate_hz
                if modality == "eeg":
                    channel_coverage = channel_coverage and all(
                        channel_counts[channel] >= expected_count * 0.8
                        for channel in expected_channels
                    )
                else:
                    channel_coverage = len(clean) >= expected_count * 0.8
            coverage = (
                max(s.timestamp for s in clean) - min(s.timestamp for s in clean) if clean else 0
            )
            if (
                len(clean) >= 2
                and degraded <= max_degraded_fraction
                and coverage >= 0.8 * epoch_s
                and channel_coverage
            ):
                value = epoch_value(modality, component, clean, check_budget=check_budget)
            values.append(value if value is None or isfinite(value) else None)
            counts.append(len(clean) if value is not None else 0)
        unit = (
            "captured_voltage_unit^2"
            if modality == "eeg"
            else "ms"
            if component.startswith("hrv_")
            else "beats/min"
            if component == "heart_rate_bpm"
            else "uS"
            if modality == "eda"
            else "breaths/min"
            if component == "respiration_rate"
            else amplitude_unit
        )
        result.append(
            FeatureSeries(modality, component, unit, tuple(values), tuple(counts), origin, epoch_s)
        )
    return tuple(result)
