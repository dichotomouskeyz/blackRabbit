"""Temporal window helpers for ARC event-locked queries.

These helpers produce absolute LSL-time windows centered on an ECHO anchor
timestamp. They are intentionally small and computation-neutral so ARC batch
code can reuse the same W1/W2/W3 ranges for EEG, HRV, EDA, and respiration.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from batch.arc_models import ARC_WINDOWS, ARCWindowName

CANONICAL_CENTERED_WINDOW_WIDTHS_S: dict[ARCWindowName, float] = {
    "w1": 30.0,
    "w2": 120.0,
    "w3": 300.0,
}
CANONICAL_CENTERED_WINDOW_LABELS: dict[ARCWindowName, str] = {
    "w1": "narrow",
    "w2": "medium",
    "w3": "wide",
}


@dataclass(frozen=True, slots=True)
class ARCWindowBounds:
    """Absolute LSL-time bounds for one ARC temporal window."""

    name: ARCWindowName
    label: str
    center_lsl_timestamp: float
    start_lsl_timestamp: float
    end_lsl_timestamp: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("center_lsl_timestamp", self.center_lsl_timestamp),
            ("start_lsl_timestamp", self.start_lsl_timestamp),
            ("end_lsl_timestamp", self.end_lsl_timestamp),
        ):
            if not isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if self.end_lsl_timestamp <= self.start_lsl_timestamp:
            raise ValueError("ARC window end must be after start")
        if not (self.start_lsl_timestamp <= self.center_lsl_timestamp <= self.end_lsl_timestamp):
            raise ValueError("ARC window must contain its center timestamp")

    @property
    def width_s(self) -> float:
        return self.end_lsl_timestamp - self.start_lsl_timestamp

    def contains(self, lsl_timestamp: float, *, include_end: bool = False) -> bool:
        """Return whether an LSL timestamp falls inside this window.

        The default is half-open `[start, end)`, which composes cleanly with SQL
        time-range queries and avoids double-counting samples exactly on a
        boundary. Set `include_end=True` for display or one-off containment checks.
        """
        if include_end:
            return self.start_lsl_timestamp <= lsl_timestamp <= self.end_lsl_timestamp
        return self.start_lsl_timestamp <= lsl_timestamp < self.end_lsl_timestamp

    def as_sql_params(self) -> tuple[float, float]:
        """Return `(start, end)` for `lsl_timestamp >= start AND < end` queries."""
        return self.start_lsl_timestamp, self.end_lsl_timestamp


def centered_arc_window(
    echo_lsl_timestamp: float,
    name: ARCWindowName,
    width_s: float,
    label: str | None = None,
) -> ARCWindowBounds:
    """Build one centered ARC window around an ECHO LSL timestamp."""
    if not isfinite(echo_lsl_timestamp):
        raise ValueError("echo_lsl_timestamp must be finite")
    if not isfinite(width_s) or width_s <= 0.0:
        raise ValueError("width_s must be finite and positive")

    half_width = width_s / 2.0
    return ARCWindowBounds(
        name=name,
        label=label or CANONICAL_CENTERED_WINDOW_LABELS[name],
        center_lsl_timestamp=echo_lsl_timestamp,
        start_lsl_timestamp=echo_lsl_timestamp - half_width,
        end_lsl_timestamp=echo_lsl_timestamp + half_width,
    )


def centered_w1(echo_lsl_timestamp: float) -> ARCWindowBounds:
    """Narrow 30s ARC window centered on the ECHO timestamp."""
    return centered_arc_window(
        echo_lsl_timestamp,
        "w1",
        CANONICAL_CENTERED_WINDOW_WIDTHS_S["w1"],
    )


def centered_w2(echo_lsl_timestamp: float) -> ARCWindowBounds:
    """Medium 120s ARC window centered on the ECHO timestamp."""
    return centered_arc_window(
        echo_lsl_timestamp,
        "w2",
        CANONICAL_CENTERED_WINDOW_WIDTHS_S["w2"],
    )


def centered_w3(echo_lsl_timestamp: float) -> ARCWindowBounds:
    """Wide 300s ARC window centered on the ECHO timestamp."""
    return centered_arc_window(
        echo_lsl_timestamp,
        "w3",
        CANONICAL_CENTERED_WINDOW_WIDTHS_S["w3"],
    )


def centered_arc_windows(
    echo_lsl_timestamp: float,
    widths_s: dict[ARCWindowName, float] | None = None,
) -> tuple[ARCWindowBounds, ARCWindowBounds, ARCWindowBounds]:
    """Return ordered W1/W2/W3 windows centered on an ECHO timestamp."""
    widths = widths_s or CANONICAL_CENTERED_WINDOW_WIDTHS_S
    missing = set(ARC_WINDOWS) - set(widths)
    if missing:
        raise ValueError(f"missing ARC window widths: {sorted(missing)}")
    return (
        centered_arc_window(echo_lsl_timestamp, "w1", widths["w1"]),
        centered_arc_window(echo_lsl_timestamp, "w2", widths["w2"]),
        centered_arc_window(echo_lsl_timestamp, "w3", widths["w3"]),
    )
