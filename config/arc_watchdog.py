"""ARC watchdog configuration loader.

The TOML file is configuration, not processing logic. In 1a it gives the
post-session ARC path a stable, versioned contract for baseline windows,
temporal windows, FDR policy, and signal availability rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
import tomllib

DEFAULT_CONFIG_PATH = Path(__file__).with_name("arc_watchdog_config.toml")
REQUIRED_WINDOWS = ("w1", "w2", "w3")
REQUIRED_MODALITIES = ("eeg", "hrv", "eda", "respiration")


@dataclass(frozen=True)
class ARCWatchdogConfig:
    path: Path
    raw: dict[str, Any]
    content_sha256: str

    @property
    def config_version(self) -> str:
        return str(self.raw["config_version"])

    @property
    def version_label(self) -> str:
        return f"{self.path.name}@{self.config_version}"


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
            raise ValueError(
                f"baseline.min_sample_count.{modality} must be a positive integer"
            )

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
    _require_text(null_model, "method")
    permutation_count = null_model.get("permutation_count")
    if not isinstance(permutation_count, int) or permutation_count <= 0:
        raise ValueError("null_model.permutation_count must be a positive integer")

    signal_components = _require_mapping(config, "signal_components")
    for modality in REQUIRED_MODALITIES:
        components = signal_components.get(modality)
        if not isinstance(components, list) or not components:
            raise ValueError(f"signal_components.{modality} must be a non-empty list")
        if not all(isinstance(component, str) and component for component in components):
            raise ValueError(f"signal_components.{modality} must contain text values")

    sap = _require_mapping(config, "signal_availability_profile")
    min_modalities = sap.get("min_modalities_required")
    if not isinstance(min_modalities, int) or not (
        1 <= min_modalities <= len(REQUIRED_MODALITIES)
    ):
        raise ValueError(
            "signal_availability_profile.min_modalities_required must be between 1 and 4"
        )
    if sap.get("require_echo_event") is not True:
        raise ValueError("signal_availability_profile.require_echo_event must be true")
    if sap.get("missing_signal_policy") != "record_available_only":
        raise ValueError(
            "signal_availability_profile.missing_signal_policy must be "
            "'record_available_only'"
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
    if not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return float(value)
