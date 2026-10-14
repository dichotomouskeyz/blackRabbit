"""Transport observations only. No device connection or identity confirmation."""

import asyncio
import importlib
from dataclasses import asdict, dataclass, replace
from typing import Any

from capture.hardware.profiles import DeviceProfile
from config import settings


@dataclass(frozen=True)
class Candidate:
    transport: str
    address: str
    name: str | None
    identifiers: dict[str, Any]
    possible_profiles: tuple[str, ...] = ()
    identity_confirmed: bool = False


@dataclass(frozen=True)
class BackendResult:
    backend: str
    status: str
    candidates: tuple[Candidate, ...] = ()
    error_type: str | None = None


def _failure(backend: str, exc: Exception) -> BackendResult:
    categories = {
        ModuleNotFoundError: "missing_dependency",
        ImportError: "missing_dependency",
        PermissionError: "permission_denied",
        OSError: "unavailable",
    }
    status = next((value for kind, value in categories.items() if isinstance(exc, kind)), "failed")
    # Bleak's platform errors expose differing types/messages. Avoid leaking messages/addresses.
    reason = getattr(exc, "reason", None)
    if reason is not None:
        code = getattr(reason, "name", "")
        status = "permission_denied" if code.startswith("DENIED_") else "unavailable"
    dbus_error = getattr(exc, "dbus_error", "")
    if dbus_error in {"org.bluez.Error.NotAuthorized", "org.freedesktop.DBus.Error.AccessDenied"}:
        status = "permission_denied"
    elif dbus_error in {"org.bluez.Error.NotReady", "org.freedesktop.DBus.Error.ServiceUnknown"}:
        status = "unavailable"
    return BackendResult(backend, status, error_type=type(exc).__name__)


def _serial_candidates() -> tuple[Candidate, ...]:
    ports = importlib.import_module("serial.tools.list_ports").comports()
    candidates = []
    for port in ports:
        # USB discovery intentionally excludes non-USB serial devices.
        if port.vid is None or port.pid is None:
            continue
        candidates.append(
            Candidate(
                "usb_serial",
                port.device,
                port.description,
                {
                    "vid_pid": f"{port.vid:04x}:{port.pid:04x}",
                    "serial_number": port.serial_number,
                    "manufacturer": port.manufacturer,
                    "product": port.product,
                },
            )
        )
    return tuple(sorted(candidates, key=lambda c: c.address))


async def _ble_candidates(timeout: float) -> tuple[Candidate, ...]:
    scanner = importlib.import_module("bleak").BleakScanner
    found = await scanner.discover(timeout=timeout, return_adv=True)
    return tuple(
        sorted(
            (
                Candidate(
                    "ble",
                    device.address,
                    advert.local_name or device.name,
                    {
                        "service_uuids": sorted(u.lower() for u in advert.service_uuids),
                        "manufacturer_ids": sorted(advert.manufacturer_data),
                        "rssi": advert.rssi,
                    },
                )
                for device, advert in found.values()
            ),
            key=lambda c: c.address,
        )
    )


def _with_matches(candidate: Candidate, profiles: tuple[DeviceProfile, ...]) -> Candidate:
    values = {
        "name": [candidate.name or ""],
        "vid_pid": [candidate.identifiers.get("vid_pid", "")],
        "service_uuid": candidate.identifiers.get("service_uuids", []),
    }
    matches = {
        f"{profile.id}@{profile.version}"
        for profile in profiles
        if any(
            h.transport == candidate.transport
            and h.value.casefold() in {v.casefold() for v in values[h.field]}
            for h in profile.discovery_hints
        )
    }
    return replace(candidate, possible_profiles=tuple(sorted(matches)))


async def discover(
    *,
    backends: tuple[str, ...] = ("usb_serial", "ble"),
    profiles: tuple[DeviceProfile, ...] = (),
) -> dict:
    """Bounded scan. A backend failure does not discard another backend's results."""
    settings.validate_hardware()
    if not backends or set(backends) - {"usb_serial", "ble"}:
        from capture.hardware.errors import ValidationError

        raise ValidationError("Choose usb_serial and/or ble discovery")

    async def scan(backend: str) -> BackendResult:
        try:
            if backend == "usb_serial":
                candidates = await asyncio.to_thread(_serial_candidates)
            else:
                candidates = await asyncio.wait_for(
                    _ble_candidates(settings.HARDWARE_BLE_SCAN_SECONDS),
                    timeout=settings.HARDWARE_BLE_SCAN_SECONDS + 2,
                )
            return BackendResult(
                backend, "ok", tuple(_with_matches(c, profiles) for c in candidates)
            )
        except Exception as exc:
            # Backend boundary: SDK/platform exceptions are returned, never hidden as empty scans.
            return _failure(backend, exc)

    results = await asyncio.gather(*(scan(b) for b in dict.fromkeys(backends)))
    return {"schema_version": 1, "backends": [asdict(r) for r in results]}
