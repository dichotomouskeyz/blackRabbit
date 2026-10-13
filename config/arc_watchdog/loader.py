from __future__ import annotations

import tomllib
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any

from config.arc_watchdog.models import ARCWatchdogConfig

# config/arc_watchdog_config.toml lives one directory above this package
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "arc_watchdog_config.toml"

REQUIRED_WINDOWS = ("w1", "w2", "w3")
REQUIRED_MODALITIES = ("eeg", "hrv", "eda", "respiration")

_VALID_EVENT_TYPES: frozenset[str] = frozenset({"zone_enter", "zone_exit", "manual_marker"})
_VALID_ZONE_LABELS: frozenset[str] = frozenset(
    {
        "arms_reach",
        "in_room",
        "leaving_room",
        "out_of_room",
        "dose_administration",
        "session_note",
        "participant_note",
        "environmental_note",
    }
)


def load_arc_watchdog_config(path: str | Path | None = None) -> ARCWatchdogConfig:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    payload = config_path.read_bytes()
    loaded = tomllib.loads(payload.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("ARC watchdog config must be a TOML mapping")
    _validate_config(loaded)
    return ARCWatchdogConfig(
        path=config_path,
        raw=loaded,
        content_sha256=sha256(payload).hexdigest(),
    )


def _validate_config(config: dict[str, Any]) -> None:
    _require_text(config, "config_version")
    if config.get("config_role") != "arc_watchdog":
        raise ValueError("config_role must be 'arc_watchdog'")

    baseline = _require_mapping(config, "baseline")
    window_duration = _require_number(baseline, "window_duration_s")
    if window_duration <= 0:
        raise ValueError("baseline.window_duration_s must be positive")

    min_sample_count = _require_mapping(baseline, "min_sample_count")
    for modality in REQUIRED_MODALITIES:
        count = min_sample_count.get(modality)
        if not isinstance(count, int) or count <= 0:
            raise ValueError(f"baseline.min_sample_count.{modality} must be a positive integer")

    windows = _require_mapping(config, "windows")
    previous_end = -1.0
    for name in REQUIRED_WINDOWS:
        window = _require_mapping(windows, name)
        _require_text(window, "label")
        start_s = _require_number(window, "start_s")
        end_s = _require_number(window, "end_s")
        if start_s < 0 or end_s <= start_s:
            raise ValueError(f"windows.{name} must satisfy 0 <= start_s < end_s")
        if start_s < previous_end:
            raise ValueError("ARC windows must be ordered and non-overlapping")
        previous_end = end_s

    fdr = _require_mapping(config, "fdr")
    if fdr.get("method") != "benjamini_hochberg":
        raise ValueError("fdr.method must be 'benjamini_hochberg'")
    alpha = _require_number(fdr, "alpha")
    if not (0 < alpha <= 1):
        raise ValueError("fdr.alpha must be > 0 and <= 1")
    if fdr.get("family_scope") != "session":
        raise ValueError("fdr.family_scope must be 'session'")

    null_model = _require_mapping(config, "null_model")
    method = _require_text(null_model, "method")
    if method != "circular_shift":
        raise ValueError("null_model.method must be circular_shift")
    permutation_count = null_model.get("permutation_count")
    if not isinstance(permutation_count, int) or permutation_count < 100:
        raise ValueError("null_model.permutation_count must be an integer >= 100")
    if method == "circular_shift":
        random_seed = null_model.get("random_seed")
        if isinstance(random_seed, bool) or not isinstance(random_seed, int) or random_seed < 0:
            raise ValueError("null_model.random_seed must be a nonnegative integer")

    from batch.arc.features import COMPONENTS

    features = _require_mapping(config, "features")
    epoch = _require_number(features, "epoch_s")
    if epoch <= 0 or window_duration < 2 * epoch:
        raise ValueError("features.epoch_s must be positive with at least two baseline epochs")
    quality = _require_mapping(config, "quality")
    fraction = _require_number(quality, "max_degraded_fraction")
    if not 0 <= fraction < 1:
        raise ValueError("quality.max_degraded_fraction must be in [0,1)")
    participation = _require_mapping(config, "participation")
    if _require_number(participation, "deviation_threshold") <= 0:
        raise ValueError("participation.deviation_threshold must be positive")
    review = _require_mapping(config, "review")
    if _require_number(review, "deviation_threshold") <= 0:
        raise ValueError("review.deviation_threshold must be positive")
    signal_components = _require_mapping(config, "signal_components")
    for modality in REQUIRED_MODALITIES:
        components = signal_components.get(modality)
        if not isinstance(components, list) or not components:
            raise ValueError(f"signal_components.{modality} must be a non-empty list")
        if any(c not in COMPONENTS[modality] for c in components):
            raise ValueError(f"unsupported {modality} signal component")
        if len(set(components)) != len(components):
            raise ValueError("signal components must be unique")
        if not all(isinstance(c, str) and c for c in components):
            raise ValueError(f"signal_components.{modality} must contain text values")

    sap = _require_mapping(config, "signal_availability_profile")
    min_modalities = sap.get("min_modalities_required")
    if not isinstance(min_modalities, int) or not (1 <= min_modalities <= len(REQUIRED_MODALITIES)):
        raise ValueError(
            "signal_availability_profile.min_modalities_required must be between 1 and 4"
        )
    if sap.get("require_echo_event") is not True:
        raise ValueError("signal_availability_profile.require_echo_event must be true")
    if sap.get("missing_signal_policy") != "record_available_only":
        raise ValueError(
            "signal_availability_profile.missing_signal_policy must be 'record_available_only'"
        )

    anchor = _require_mapping(config, "anchor_events")
    include = anchor.get("include")
    if not isinstance(include, list) or not include:
        raise ValueError("anchor_events.include must be a non-empty list")
    for i, entry in enumerate(include):
        if not isinstance(entry, dict):
            raise ValueError(f"anchor_events.include[{i}] must be a mapping")
        et = entry.get("event_type")
        zl = entry.get("zone_label")
        if et not in _VALID_EVENT_TYPES:
            raise ValueError(
                f"anchor_events.include[{i}].event_type '{et}' is not a valid event type"
            )
        if zl not in _VALID_ZONE_LABELS:
            raise ValueError(
                f"anchor_events.include[{i}].zone_label '{zl}' is not a valid zone label"
            )


def _require_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _require_text(parent: dict[str, Any], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty text")
    return value


def _require_number(parent: dict[str, Any], key: str) -> float:
    value = parent.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{key} must be numeric")
    return float(value)
