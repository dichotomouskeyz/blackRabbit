"""Local bindings and hardware-only configuration validation."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capture.hardware.errors import ValidationError
from capture.hardware.profiles import DeviceProfile, identifier, load_profile, synthetic_profile

_TEXT_PARAMS = frozenset(
    {
        "serial_port",
        "mac_address",
        "ip_address",
        "ip_address_aux",
        "ip_address_anc",
        "serial_number",
        "other_info",
    }
)
_INT_PARAMS = frozenset({"ip_port", "ip_port_aux", "ip_port_anc", "ip_protocol", "timeout"})
_IDENTITY_PARAMS = frozenset({"serial_port", "mac_address", "ip_address", "serial_number"})


@dataclass(frozen=True)
class DeviceBinding:
    source_id: str
    profile: DeviceProfile
    parameters: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        identifier(self.source_id)
        if not isinstance(self.profile, DeviceProfile):
            raise ValidationError("Binding requires a DeviceProfile")
        try:
            params = dict(self.parameters)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Invalid connection parameters") from exc
        if len(params) != len(self.parameters):
            raise ValidationError("Duplicate connection parameters")
        for key, value in params.items():
            if key in _TEXT_PARAMS and isinstance(value, str):
                continue
            if key in _INT_PARAMS and type(value) is int and value >= 0:
                if key == "ip_protocol" and value not in (0, 1, 2):
                    raise ValidationError("Invalid ip_protocol")
                if key.startswith("ip_port") and value > 65535:
                    raise ValidationError("Invalid IP port")
                continue
            raise ValidationError(f"Unsupported or mistyped connection parameter: {key}")
        object.__setattr__(self, "parameters", tuple(sorted(params.items())))


@dataclass(frozen=True)
class BridgeConfig:
    bindings: tuple[DeviceBinding, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValidationError("Only binding schema_version 1 is supported")
        if not isinstance(self.bindings, (list, tuple)) or not self.bindings:
            raise ValidationError("At least one device binding is required")
        object.__setattr__(self, "bindings", tuple(self.bindings))
        sources: set[str] = set()
        connections: set[tuple] = set()
        for binding in self.bindings:
            if not isinstance(binding, DeviceBinding):
                raise ValidationError("Invalid device binding")
            if binding.source_id in sources:
                raise ValidationError("Duplicate source_id")
            sources.add(binding.source_id)
            if binding.profile.board_id == -1:
                continue
            identity = tuple((k, v) for k, v in binding.parameters if k in _IDENTITY_PARAMS and v)
            # Also forbid two unspecified bindings for the same physical board model.
            keys = identity or (("board_id", binding.profile.board_id),)
            for key in keys:
                if key in connections:
                    raise ValidationError("Duplicate physical connection identity")
                connections.add(key)


def load_config(path: str | Path) -> BridgeConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if set(data) != {"schema_version", "bindings"}:
            raise ValidationError("Expected schema_version and bindings")
        bindings = []
        for item in data["bindings"]:
            if set(item) - {"source_id", "profile", "parameters"}:
                raise ValidationError("Unknown binding field")
            profile = (
                synthetic_profile()
                if item["profile"] == "builtin:synthetic"
                else load_profile(path.parent / item["profile"])
            )
            bindings.append(
                DeviceBinding(item["source_id"], profile, tuple(item.get("parameters", {}).items()))
            )
        return BridgeConfig(tuple(bindings), data["schema_version"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValidationError("Malformed binding configuration") from exc
