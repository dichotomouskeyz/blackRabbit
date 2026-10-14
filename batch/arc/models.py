"""Canonical ARC convergence event model.

ARC links one ECHO anchor event to post-event APEX physiological responses.
These dataclasses define that in-memory contract and the exact row shape used
by event_composite_profiles. They do not perform signal processing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

ARCWindowName = Literal["w1", "w2", "w3"]
APEXModality = Literal["eeg", "hrv", "eda", "respiration"]

ARC_WINDOWS: tuple[ARCWindowName, ...] = ("w1", "w2", "w3")
APEX_MODALITIES: tuple[APEXModality, ...] = ("eeg", "hrv", "eda", "respiration")
REQUIRED_ECP_DENSITY_COLUMNS: dict[ARCWindowName, str] = {
    "w1": "w1_convergence_density",
    "w2": "w2_convergence_density",
    "w3": "w3_convergence_density",
}
REQUIRED_ECP_SIGNAL_COLUMNS: dict[ARCWindowName, str] = {
    "w1": "w1_participating_signals",
    "w2": "w2_participating_signals",
    "w3": "w3_participating_signals",
}


@dataclass(frozen=True, slots=True)
class EchoAnchorEvent:
    """ECHO event that opens ARC convergence windows."""

    id: int
    session_id: str
    participant_id: str
    site_id: str
    sponsor_id: str
    event_type: str
    source: str
    actor_id: str | None
    actor_role: str
    zone_label: str
    lsl_timestamp: float


@dataclass(frozen=True, slots=True)
class APEXResponse:
    """One physiological component response inside one ARC window."""

    modality: APEXModality  # pragma: allowlist secret ("APEX" trips the Artifactory detector)
    signal_component: str
    window: ARCWindowName
    baseline_mean: float
    baseline_std: float
    observed_value: float
    sample_count: int
    z_score: float
    p_value: float
    effect_direction: Literal["increase", "decrease", "flat"] = "flat"
    metadata: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.baseline_std < 0:
            raise ValueError("baseline_std must be non-negative")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if not (0.0 <= self.p_value <= 1.0):
            raise ValueError("p_value must be between 0.0 and 1.0")
        if self.metadata and not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def arc_signal_id(self) -> str:
        """Stable signal key used in ARC JSON payloads."""
        return f"{self.modality}.{self.signal_component}"

    def to_deviation_metric(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "modality": self.modality,
            "signal_component": self.signal_component,
            "baseline_mean": self.baseline_mean,
            "baseline_std": self.baseline_std,
            "observed_value": self.observed_value,
            "sample_count": self.sample_count,
            "z_score": self.z_score,
            "p_value": self.p_value,
            "effect_direction": self.effect_direction,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class ARCWindowResponse:
    """All APEX responses for one event-locked ARC window."""

    name: ARCWindowName
    label: str
    start_s: float
    end_s: float
    convergence_density: float
    responses: tuple[APEXResponse, ...] = ()

    def __post_init__(self) -> None:
        if self.start_s < 0 or self.end_s <= self.start_s:
            raise ValueError("ARC window must satisfy 0 <= start_s < end_s")
        if self.convergence_density < 0.0:
            raise ValueError("convergence_density must be non-negative")
        if any(response.window != self.name for response in self.responses):
            raise ValueError("all APEX responses must belong to the window")

    @property
    def participating_signals(self) -> tuple[str, ...]:
        return tuple(sorted({response.arc_signal_id for response in self.responses}))

    def deviation_metrics(self) -> dict[str, dict[str, Any]]:
        return {
            response.arc_signal_id: response.to_deviation_metric() for response in self.responses
        }


@dataclass(frozen=True, slots=True)
class ARCConvergenceEvent:
    """Canonical synchronized convergence object: one ECHO anchor plus APEX response windows."""

    echo: EchoAnchorEvent
    windows: tuple[ARCWindowResponse, ARCWindowResponse, ARCWindowResponse]
    null_threshold: float
    fdr_q_value: float
    passed_fdr: bool
    sap_available_signals: tuple[str, ...]
    sap_participating_signals: tuple[str, ...]
    arc_config_version: str
    arc_config_sha256: str
    temporal_alignment_score: float | None = None

    def __post_init__(self) -> None:
        window_names = tuple(window.name for window in self.windows)
        if window_names != ARC_WINDOWS:
            raise ValueError("ARCConvergenceEvent windows must be ordered as w1, w2, w3")
        if not (0.0 <= self.null_threshold <= 1.0):
            raise ValueError("null_threshold must be between 0.0 and 1.0")
        if not (0.0 <= self.fdr_q_value <= 1.0):
            raise ValueError("fdr_q_value must be between 0.0 and 1.0")
        if self.passed_fdr is not True:
            raise ValueError("ARCConvergenceEvent only serializes FDR-passing events")
        if self.temporal_alignment_score is not None and not (
            0.0 <= self.temporal_alignment_score <= 1.0
        ):
            raise ValueError("temporal_alignment_score must be null or between 0.0 and 1.0")
        if not self.arc_config_version:
            raise ValueError("arc_config_version is required")
        if len(self.arc_config_sha256) != 64:
            raise ValueError("arc_config_sha256 must be a SHA-256 hex digest")

    @property
    def deviation_metrics(self) -> dict[str, dict[str, dict[str, Any]]]:
        return {window.name: window.deviation_metrics() for window in self.windows}

    def to_event_composite_profile_row(self) -> dict[str, Any]:
        """Serialize to the event_composite_profiles insert contract."""
        row: dict[str, Any] = {
            "session_id": self.echo.session_id,
            "participant_id": self.echo.participant_id,
            "site_id": self.echo.site_id,
            "sponsor_id": self.echo.sponsor_id,
            "echo_event_id": self.echo.id,
            "deviation_metrics": self.deviation_metrics,
            "null_threshold": self.null_threshold,
            "fdr_q_value": self.fdr_q_value,
            "passed_fdr": self.passed_fdr,
            "temporal_alignment_score": self.temporal_alignment_score,
            "sap_available_signals": list(self.sap_available_signals),
            "sap_participating_signals": list(self.sap_participating_signals),
            "arc_config_version": self.arc_config_version,
            "arc_config_sha256": self.arc_config_sha256,
        }
        for window in self.windows:
            row[REQUIRED_ECP_DENSITY_COLUMNS[window.name]] = window.convergence_density
            row[REQUIRED_ECP_SIGNAL_COLUMNS[window.name]] = list(window.participating_signals)
        return row
