"""Pure convergence statistics. All randomness is explicit and reproducible."""

from __future__ import annotations

from typing import Sequence

import numpy as np


def deviation(value: float, mean: float, std: float) -> float:
    if not np.all(np.isfinite([value, mean, std])) or std < 0:
        raise ValueError("deviation requires finite values and nonnegative SD")
    return float((value - mean) / max(std, abs(mean) * 1e-6, 1e-9))


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    p = np.asarray(p_values, dtype=float)
    if np.any(~np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("p values must be finite and between zero and one")
    if len(p) == 0:
        return []
    order = np.argsort(p, kind="stable")
    adjusted = np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    result = np.empty_like(p)
    result[order] = np.minimum(adjusted, 1)
    return result.tolist()


def empirical_p(observed: float, null: np.ndarray) -> float:
    if not np.isfinite(observed) or len(null) == 0 or not np.all(np.isfinite(null)):
        raise ValueError("empirical p requires a finite statistic and nonempty finite null")
    return float((1 + np.count_nonzero(null >= observed)) / (len(null) + 1))


def circular_means(
    values: np.ndarray, length: int, *, max_degraded_fraction: float = 0.5
) -> np.ndarray:
    """Mean for every circular starting index; unavailable if over half missing."""
    n = len(values)
    if length < 1 or length > n:
        return np.full(n, np.nan)
    twice = np.tile(values, 2)
    total = np.r_[0.0, np.cumsum(np.nan_to_num(twice, nan=0.0))]
    counts = np.r_[0, np.cumsum(np.isfinite(twice))]
    valid = counts[length : length + n] - counts[:n]
    sums = total[length : length + n] - total[:n]
    return np.divide(
        sums,
        valid,
        out=np.full(n, np.nan),
        where=valid >= np.ceil(length * (1 - max_degraded_fraction)),
    )


def convergence_statistics(
    z_by_modality: dict[str, np.ndarray], *, threshold: float, min_modalities: int
):
    """Return density and bounded strength without counting correlated components twice."""
    values = np.asarray(list(z_by_modality.values()), dtype=float)
    denominator = np.sum(np.isfinite(values), axis=0)
    numerator = np.sum(np.isfinite(values) & (values >= threshold), axis=0)
    density = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(denominator, dtype=float),
        where=denominator >= min_modalities,
    )
    strength = np.divide(
        np.sum(np.minimum(np.nan_to_num(values, nan=0), 10), axis=0),
        denominator,
        out=np.zeros_like(density),
        where=denominator > 0,
    )
    return density, density * strength


def null_densities(
    series: dict[str, tuple[str, np.ndarray, float, float]],
    windows: Sequence[tuple[int, int] | tuple[int, int, tuple[str, ...]]],
    *,
    permutations: int,
    seed: int,
    threshold: float,
    min_modalities: int,
    max_degraded_fraction: float = 0.5,
) -> np.ndarray:
    """Maximum W1/W2/W3 convergence score under independent modality circular shifts.

    Components within the same modality share the same shift. Sampling preserves
    signal order and within-modality dependence; exchangeability assumes approximate
    stationarity over the analyzed recording. This is exploratory event association.
    """
    if not series:
        return np.zeros(permutations)
    n = len(next(iter(series.values()))[1])
    rng = np.random.Generator(np.random.PCG64(seed))
    modalities = sorted({data[0] for data in series.values()})
    shifts = {m: rng.integers(0, n, size=permutations) for m in modalities}
    maximum = np.zeros(permutations)
    usable = np.ones(permutations, dtype=bool)
    for window in windows:
        start, stop = window[:2]
        keys = window[2] if len(window) == 3 else tuple(series)
        observed_modalities = sorted({series[key][0] for key in keys})
        z_by_modality = {m: np.full(permutations, np.nan) for m in modalities}
        for key in sorted(keys):
            modality, values, mean, std = series[key]
            sampled = circular_means(
                values, stop - start, max_degraded_fraction=max_degraded_fraction
            )[(start + shifts[modality]) % n]
            usable &= np.isfinite(sampled)
            z = np.abs((sampled - mean) / max(std, abs(mean) * 1e-6, 1e-9))
            z_by_modality[modality] = np.fmax(z_by_modality[modality], z)
        _, scores = convergence_statistics(
            {m: z_by_modality[m] for m in observed_modalities},
            threshold=threshold,
            min_modalities=min_modalities,
        )
        maximum = np.maximum(maximum, scores)
    maximum[~usable] = np.nan
    return maximum
