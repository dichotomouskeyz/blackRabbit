"""Deterministic post-session ARC calculation from immutable captured samples."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from batch.arc.convergence import (
    benjamini_hochberg,
    convergence_statistics,
    deviation,
    empirical_p,
    null_densities,
)
from batch.arc.features import EXTRACTOR_VERSION, feature_series
from batch.arc.storage import canonical_json

ALGORITHM_VERSION = "arc-circular-shift-1"
LIMITATIONS = [
    "Exploratory association with recorded markers; no causal or clinical inference.",
    "Circular-shift inference assumes approximate stationarity over the recording.",
    "BH assumes independent or positively dependent event tests; "
    "overlapping markers may violate this.",
    "EEG band power retains captured voltage units; calibration is not inferred.",
    "Short-epoch RR variability is descriptive and is not a clinical HRV assessment.",
    "SQI exclusions use stored flags and finite-value checks; "
    "no artifact-removal model is implied.",
]


def prepare_baselines(data, metadata, config):
    """Build one epoch timeline for both baseline and event responses."""
    finite_data = {
        m: [row for row in rows if np.isfinite(row.timestamp)] for m, rows in data.items()
    }
    present = [rows for m, rows in finite_data.items() if rows and m in metadata]
    if not present:
        raise RuntimeError("no APEX samples with session signal metadata")
    origin = min(rows[0].timestamp for rows in present)
    # Infer one sample interval per stream only to locate the recording endpoint.
    endpoints = []
    for rows in present:
        timestamps = sorted({r.timestamp for r in rows})
        step = float(np.median(np.diff(timestamps))) if len(timestamps) > 1 else 0
        endpoints.append(timestamps[-1] + step)
    end = max(endpoints)
    epoch_s = float(config.raw["features"]["epoch_s"])
    baseline_end = origin + float(config.raw["baseline"]["window_duration_s"])
    if end < baseline_end:
        raise RuntimeError("recording is shorter than the configured baseline window")
    baseline_n = int(np.floor((baseline_end - origin) / epoch_s + 1e-8))
    baselines, timelines, unavailable = [], {}, {}
    for modality in sorted(data):
        rows = finite_data[modality]
        if modality not in metadata or not rows:
            unavailable[modality] = "missing_metadata_or_samples"
            continue
        series = feature_series(
            modality,
            rows,
            config.raw["signal_components"][modality],
            origin=origin,
            end=end,
            epoch_s=epoch_s,
            max_degraded_fraction=config.raw["quality"]["max_degraded_fraction"],
            amplitude_unit=metadata[modality].get("respiration_unit") or "captured_amplitude_unit",
        )
        for signal in series:
            key = f"{modality}.{signal.component}"
            valid = [v for v in signal.values[:baseline_n] if v is not None]
            count = sum(signal.counts[:baseline_n])
            if len(valid) < 2 or count < config.raw["baseline"]["min_sample_count"][modality]:
                unavailable[key] = "insufficient_valid_baseline_epochs_or_samples"
                continue
            baseline = dict(
                modality=modality,
                signal_component=signal.component,
                baseline_mean=float(np.mean(valid)),
                baseline_std=float(np.std(valid, ddof=1)),
                baseline_window_start=origin,
                baseline_window_end=baseline_end,
                sample_count=count,
                epoch_count=len(valid),
                units=signal.unit,
                extractor_version=EXTRACTOR_VERSION,
                config_version=config.config_version,
                config_sha256=config.content_sha256,
            )
            baselines.append(baseline)
            timelines[key] = signal
    if (
        len({b["modality"] for b in baselines})
        < config.raw["signal_availability_profile"]["min_modalities_required"]
    ):
        raise RuntimeError("insufficient modalities with usable persisted-baseline inputs")
    return origin, end, baselines, timelines, unavailable


def analyze_recording(identity, data, metadata, anchors, config, input_sha256, safety=()):
    """Return deterministic report, baseline records and FDR-passing ECP projections."""
    origin, end, baselines, timelines, unavailable = prepare_baselines(data, metadata, config)
    epoch_s = float(config.raw["features"]["epoch_s"])
    min_modalities = config.raw["signal_availability_profile"]["min_modalities_required"]
    threshold = config.raw["participation"]["deviation_threshold"]
    baseline_map = {f"{b['modality']}.{b['signal_component']}": b for b in baselines}
    null_series = {
        key: (
            signal.modality,
            np.array(signal.values, dtype=float),
            baseline_map[key]["baseline_mean"],
            baseline_map[key]["baseline_std"],
        )
        for key, signal in timelines.items()
    }
    events: list[dict[str, Any]] = []
    for anchor in anchors:
        windows: dict[str, Any] = {}
        null_windows: list[tuple[int, int, tuple[str, ...]]] = []
        for name in ("w1", "w2", "w3"):
            window = config.raw["windows"][name]
            start = anchor.lsl_timestamp + window["start_s"]
            stop = anchor.lsl_timestamp + window["end_s"]
            first = int(np.ceil((start - origin) / epoch_s - 1e-8))
            last = int(np.floor((stop - origin) / epoch_s + 1e-8))
            metrics, excluded = {}, {}
            complete = start >= origin and stop <= end + 1e-8 and last > first
            if complete:
                for key, signal in sorted(timelines.items()):
                    values = signal.values[first:last]
                    valid = [value for value in values if value is not None]
                    if not values or len(valid) / len(values) < (
                        1 - config.raw["quality"]["max_degraded_fraction"]
                    ):
                        excluded[key] = "degraded_or_missing_epochs"
                        continue
                    baseline = baseline_map[key]
                    observed = float(np.mean(valid))
                    z = deviation(observed, baseline["baseline_mean"], baseline["baseline_std"])
                    metrics[key] = dict(
                        observed_value=observed,
                        units=signal.unit,
                        baseline_mean=baseline["baseline_mean"],
                        baseline_std=baseline["baseline_std"],
                        deviation=z,
                        epoch_count=len(valid),
                        sample_count=sum(signal.counts[first:last]),
                        participates=abs(z) >= threshold,
                    )
            available_modalities = {key.split(".")[0] for key in metrics}
            participating = [key for key, metric in metrics.items() if metric["participates"]]
            eligible = complete and len(available_modalities) >= min_modalities
            z_by_modality = {
                modality: np.array(
                    [
                        max(
                            abs(metric["deviation"])
                            for key, metric in metrics.items()
                            if key.split(".")[0] == modality
                        )
                    ]
                )
                for modality in sorted(available_modalities)
            }
            density, score = 0.0, 0.0
            if eligible:
                densities, scores = convergence_statistics(
                    z_by_modality, threshold=threshold, min_modalities=min_modalities
                )
                density, score = float(densities[0]), float(scores[0])
            windows[name] = dict(
                start_lsl_timestamp=start,
                end_lsl_timestamp=stop,
                eligible=eligible,
                exclusion_reason=None
                if eligible
                else "incomplete_window_or_insufficient_modalities",
                convergence_density=density,
                convergence_score=score,
                metrics=metrics,
                participating_signals=participating,
                excluded_signals=excluded,
            )
            if eligible:
                null_windows.append((first, last, tuple(sorted(metrics))))
        score = max(w["convergence_score"] for w in windows.values())
        null = null_densities(
            null_series,
            null_windows,
            permutations=config.raw["null_model"]["permutation_count"],
            seed=config.raw["null_model"]["random_seed"],
            threshold=threshold,
            min_modalities=min_modalities,
            max_degraded_fraction=config.raw["quality"]["max_degraded_fraction"],
        )
        valid_null = null[np.isfinite(null)]
        min_null = max(100, int(np.ceil(len(null) / 2)))
        testable = bool(null_windows) and len(valid_null) >= min_null
        p = empirical_p(score, valid_null) if testable else 1.0
        events.append(
            dict(
                echo_event_id=anchor.id,
                lsl_timestamp=anchor.lsl_timestamp,
                event_type=anchor.event_type,
                zone_label=anchor.zone_label,
                windows=windows,
                statistic=score,
                p_value=p,
                null_valid_count=len(valid_null),
                null_excluded_count=len(null) - len(valid_null),
                testable=testable,
                test_exclusion_reason=None
                if testable
                else "insufficient_valid_surrogates_or_windows",
            )
        )
    q_values = benjamini_hochberg([event["p_value"] for event in events])
    interpretations, ecps = [], []
    for event, q in zip(events, q_values):
        event["fdr_q_value"] = q
        event["passed_fdr"] = q <= config.raw["fdr"]["alpha"] and event["statistic"] > 0
        if not event["passed_fdr"]:
            continue
        available, participants = set(), set()
        ecp: dict[str, Any] = dict(
            **identity,
            echo_event_id=event["echo_event_id"],
            deviation_metrics={name: w["metrics"] for name, w in event["windows"].items()},
            null_threshold=config.raw["fdr"]["alpha"],
            fdr_q_value=q,
            passed_fdr=True,
            temporal_alignment_score=None,
            arc_config_version=config.config_version,
            arc_config_sha256=config.content_sha256,
        )
        for name, window in event["windows"].items():
            ecp[f"{name}_convergence_density"] = window["convergence_density"]
            ecp[f"{name}_participating_signals"] = window["participating_signals"]
            available.update(window["metrics"])
            participants.update(window["participating_signals"])
            for key in window["participating_signals"]:
                metric = window["metrics"][key]
                interpretations.append(
                    dict(
                        echo_event_id=event["echo_event_id"],
                        window=name,
                        signal_component=key,
                        metric="observed_value",
                        value=metric["observed_value"],
                        units=metric["units"],
                        baseline_mean=metric["baseline_mean"],
                        deviation=metric["deviation"],
                        fdr_q_value=q,
                    )
                )
        ecp["sap_available_signals"] = sorted(available)
        ecp["sap_participating_signals"] = sorted(participants)
        ecps.append(ecp)
    for baseline in baselines:
        baseline["input_sha256"] = input_sha256
    quality = {}
    excursions = []
    review_threshold = config.raw["review"]["deviation_threshold"]
    for modality, rows in sorted(data.items()):
        quality[modality] = dict(
            sample_count=len(rows),
            flagged_sample_count=sum(row.flagged for row in rows),
            invalid_value_count=sum(
                bool(not np.isfinite(row.value) or (modality == "hrv" and row.value <= 0))
                for row in rows
            ),
            invalid_timestamp_count=sum(not bool(np.isfinite(row.timestamp)) for row in rows),
        )
    for key, timeline in sorted(timelines.items()):
        baseline = baseline_map[key]
        for index, value in enumerate(timeline.values):
            if value is None:
                continue
            z = deviation(value, baseline["baseline_mean"], baseline["baseline_std"])
            if abs(z) >= review_threshold:
                excursions.append(
                    dict(
                        signal_component=key,
                        start_lsl_timestamp=origin + index * epoch_s,
                        value=value,
                        units=timeline.unit,
                        deviation=z,
                    )
                )
    artifact: dict[str, Any] = dict(
        schema_version=1,
        identity=identity,
        algorithm_version=ALGORITHM_VERSION,
        extractor_version=EXTRACTOR_VERSION,
        numerical_runtime={"numpy": np.__version__},
        config_version=config.config_version,
        config_sha256=config.content_sha256,
        config=config.raw,
        input_sha256=input_sha256,
        baseline=baselines,
        unavailable_signals=unavailable,
        events=events,
        interpretation=interpretations,
        safety_alerts=list(safety),
        quality_summary=quality,
        data_excursion_review=dict(
            algorithm="epoch-deviation-review-1",
            threshold=review_threshold,
            findings=excursions,
            meaning="Descriptive changes relative to baseline, not clinical safety alerts",
        ),
        safety_assessment="Not performed; existing safety alerts are reproduced with provenance",
        limitations=LIMITATIONS,
    )
    content_hash = hashlib.sha256(canonical_json(artifact).encode()).hexdigest()
    artifact["analysis_id"] = str(uuid5(NAMESPACE_URL, "blackRabbit:" + content_hash))
    return artifact, baselines, ecps
