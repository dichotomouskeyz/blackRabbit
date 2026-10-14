"""Portable, declarative source mappings. Loading never connects to a device."""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from capture.hardware.errors import ValidationError

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
_SIGNAL_TYPES = {"EEG", "ECG", "EMG", "EOG", "EDA", "PPG", "Respiration", "HRV", "AUX"}
_ORIGINS = {"host_receipt", "device_sample", "unknown", "simulated"}


def identifier(value: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValidationError("Identifiers require 1-64 letters, digits, underscores or hyphens")


def finite_number(value: float, field: str, *, positive: bool = False) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValidationError(f"{field} must be a finite number")
    if positive and value <= 0:
        raise ValidationError(f"{field} must be positive")


def _strings(values, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValidationError(f"{field} must be a nonempty array")
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValidationError(f"{field} must contain nonempty strings")
    return tuple(values)


@dataclass(frozen=True)
class SignalProfile:
    id: str
    signal_type: str
    rows: tuple[int, ...]
    labels: tuple[str, ...]
    source_units: tuple[str, ...]
    units: tuple[str, ...]
    quantity: str = "waveform"
    scale: float = 1.0
    offset: float = 0.0
    conversion_reference: str = ""

    def __post_init__(self) -> None:
        identifier(self.id)
        if self.signal_type not in _SIGNAL_TYPES:
            raise ValidationError("Unsupported signal_type")
        if not isinstance(self.rows, (tuple, list)) or not self.rows:
            raise ValidationError("rows must be a nonempty array")
        if any(type(row) is not int or row < 0 for row in self.rows):
            raise ValidationError("rows must contain nonnegative integers")
        object.__setattr__(self, "rows", tuple(self.rows))
        if len(set(self.rows)) != len(self.rows):
            raise ValidationError("Duplicate rows in signal")
        for field in ("labels", "source_units", "units"):
            values = _strings(getattr(self, field), field)
            if len(values) != len(self.rows):
                raise ValidationError(f"{field} count must match rows")
            object.__setattr__(self, field, values)
        if len(set(self.labels)) != len(self.labels):
            raise ValidationError("Duplicate channel labels")
        if self.quantity not in {"waveform", "device_beat_interval", "auxiliary"}:
            raise ValidationError("Unsupported source quantity")
        finite_number(self.scale, "scale")
        finite_number(self.offset, "offset")
        if self.scale == 0:
            raise ValidationError("scale cannot discard the source signal")
        if not isinstance(self.conversion_reference, str):
            raise ValidationError("conversion_reference must be text")
        converted = self.scale != 1 or self.offset != 0 or self.source_units != self.units
        if converted and not self.conversion_reference.strip():
            raise ValidationError("Unit conversions require a reference")
        if self.signal_type == "HRV":
            if self.quantity != "device_beat_interval" or self.units != ("ms",):
                raise ValidationError("HRV requires one device-provided beat interval in ms")
        elif self.quantity == "device_beat_interval":
            raise ValidationError("Device beat intervals must use HRV type")


@dataclass(frozen=True)
class PresetProfile:
    preset: int
    sampling_rate: float
    timestamp_origin: str
    signals: tuple[SignalProfile, ...]

    def __post_init__(self) -> None:
        if type(self.preset) is not int or self.preset not in (0, 1, 2):
            raise ValidationError("Unsupported BrainFlow preset")
        finite_number(self.sampling_rate, "sampling_rate", positive=True)
        if self.timestamp_origin not in _ORIGINS:
            raise ValidationError("Unsupported timestamp_origin")
        if not self.signals or any(not isinstance(s, SignalProfile) for s in self.signals):
            raise ValidationError("A preset requires signal profiles")
        object.__setattr__(self, "signals", tuple(self.signals))
        rows = [r for signal in self.signals for r in signal.rows]
        if len(rows) != len(set(rows)):
            raise ValidationError("Overlapping signal assignments within a preset")


@dataclass(frozen=True)
class Evidence:
    kind: str
    reference: str
    note: str

    def __post_init__(self) -> None:
        if self.kind not in {"documentation", "simulated_verification", "physical_test"}:
            raise ValidationError("Unsupported evidence kind")
        _strings((self.reference, self.note), "evidence")


@dataclass(frozen=True)
class DiscoveryHint:
    transport: str
    field: str
    value: str

    def __post_init__(self) -> None:
        allowed = {"usb_serial": {"vid_pid", "name"}, "ble": {"service_uuid", "name"}}
        if self.transport not in allowed or self.field not in allowed[self.transport]:
            raise ValidationError("Unsupported discovery hint")
        _strings((self.value,), "discovery hint")


@dataclass(frozen=True)
class DeviceProfile:
    schema_version: int
    id: str
    version: str
    board_id: int
    presets: tuple[PresetProfile, ...]
    evidence: tuple[Evidence, ...]
    discovery_hints: tuple[DiscoveryHint, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValidationError("Only profile schema_version 1 is supported")
        identifier(self.id)
        if not isinstance(self.version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            raise ValidationError("Profile version must use major.minor.patch")
        if type(self.board_id) is not int or self.board_id < -1:
            raise ValidationError("Use a physical board ID or the synthetic board (-1)")
        for field, expected in (
            ("presets", PresetProfile),
            ("evidence", Evidence),
            ("discovery_hints", DiscoveryHint),
        ):
            values = getattr(self, field)
            if not isinstance(values, (tuple, list)) or any(
                not isinstance(v, expected) for v in values
            ):
                raise ValidationError(f"Invalid {field}")
            object.__setattr__(self, field, tuple(values))
        if not self.presets or not self.evidence:
            raise ValidationError("Profiles require presets and evidence")
        preset_ids = [p.preset for p in self.presets]
        signal_ids = [s.id for p in self.presets for s in p.signals]
        if len(set(preset_ids)) != len(preset_ids) or len(set(signal_ids)) != len(signal_ids):
            raise ValidationError("Duplicate preset or signal ID")
        if self.board_id == -1 and any(p.timestamp_origin != "simulated" for p in self.presets):
            raise ValidationError("Synthetic board timestamps must be labelled simulated")
        if self.board_id != -1 and any(p.timestamp_origin == "simulated" for p in self.presets):
            raise ValidationError("Physical board timestamps cannot be labelled simulated")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def content_hash(self) -> str:
        content = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(content.encode()).hexdigest()


def profile_from_dict(data: dict) -> DeviceProfile:
    try:
        return DeviceProfile(
            **{
                **data,
                "presets": tuple(
                    PresetProfile(
                        **{
                            **preset,
                            "signals": tuple(SignalProfile(**s) for s in preset["signals"]),
                        }
                    )
                    for preset in data["presets"]
                ),
                "evidence": tuple(Evidence(**e) for e in data["evidence"]),
                "discovery_hints": tuple(
                    DiscoveryHint(**h) for h in data.get("discovery_hints", [])
                ),
            }
        )
    except (TypeError, KeyError, AttributeError) as exc:
        raise ValidationError("Malformed profile or unknown profile fields") from exc


def load_profile(path: str | Path) -> DeviceProfile:
    try:
        return profile_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ValidationError("Cannot read profile JSON") from exc


def synthetic_profile() -> DeviceProfile:
    raw = files("capture.hardware").joinpath("profiles/synthetic.json").read_text(encoding="utf-8")
    return profile_from_dict(json.loads(raw))
