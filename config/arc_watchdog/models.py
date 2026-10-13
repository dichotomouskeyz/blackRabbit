from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AnchorEventFilter:
    """One (event_type, zone_label) pair that qualifies as an ARC anchor."""

    event_type: str
    zone_label: str


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

    @property
    def anchor_events(self) -> tuple[AnchorEventFilter, ...]:
        return tuple(
            AnchorEventFilter(event_type=e["event_type"], zone_label=e["zone_label"])
            for e in self.raw["anchor_events"]["include"]
        )
