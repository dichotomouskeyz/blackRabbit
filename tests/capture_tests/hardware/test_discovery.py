"""HW-005..006: observations and explicit backend failures."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from capture.hardware import discovery
from capture.hardware.profiles import DiscoveryHint, synthetic_profile


@pytest.mark.parametrize(
    "reason,status",
    [
        ("NO_BLUETOOTH", "unavailable"),
        ("NO_BLE_CENTRAL_ROLE", "unavailable"),
        ("POWERED_OFF", "unavailable"),
        ("DENIED_BY_USER", "permission_denied"),
        ("DENIED_BY_SYSTEM", "permission_denied"),
        ("DENIED_BY_UNKNOWN", "permission_denied"),
        ("UNKNOWN", "unavailable"),
    ],
)
def test_bleak_native_reason_classification(reason, status):
    errors = pytest.importorskip("bleak.exc")
    failure = errors.BleakBluetoothNotAvailableError(
        "test failure", getattr(errors.BleakBluetoothNotAvailableReason, reason)
    )
    assert discovery._failure("ble", failure).status == status


@pytest.mark.asyncio
async def test_empty_scan_is_success(monkeypatch):
    monkeypatch.setattr(discovery, "_serial_candidates", lambda: ())
    result = await discovery.discover(backends=("usb_serial",))
    assert result["backends"][0]["status"] == "ok"
    assert result["backends"][0]["candidates"] == ()


@pytest.mark.parametrize(
    "exception,status",
    [
        (ModuleNotFoundError(), "missing_dependency"),
        (PermissionError(), "permission_denied"),
        (OSError(), "unavailable"),
        (RuntimeError(), "failed"),
    ],
)
@pytest.mark.asyncio
async def test_backend_failure_does_not_discard_other_results(exception, status, monkeypatch):
    def broken():
        raise exception

    async def healthy(timeout):
        return (discovery.Candidate("ble", "opaque-platform-id", "Device", {}),)

    monkeypatch.setattr(discovery, "_serial_candidates", broken)
    monkeypatch.setattr(discovery, "_ble_candidates", healthy)
    result = await discovery.discover()
    assert result["backends"][0]["status"] == status
    assert result["backends"][1]["status"] == "ok"
    assert len(result["backends"][1]["candidates"]) == 1


@pytest.mark.asyncio
async def test_ambiguous_matches_never_confirm_identity(monkeypatch):
    candidate = discovery.Candidate(
        "usb_serial", "COM4", "Shared adapter", {"vid_pid": "0403:6015"}
    )
    monkeypatch.setattr(discovery, "_serial_candidates", lambda: (candidate,))
    hint = DiscoveryHint("usb_serial", "vid_pid", "0403:6015")
    profiles = tuple(
        replace(synthetic_profile(), id=name, discovery_hints=(hint,))
        for name in ("example-a", "example-b")
    )
    result = await discovery.discover(backends=("usb_serial",), profiles=profiles)
    found = result["backends"][0]["candidates"][0]
    assert len(found["possible_profiles"]) == 2
    assert found["identity_confirmed"] is False


def test_serial_enumeration_does_not_open_ports(monkeypatch):
    usb = SimpleNamespace(
        device="COM7",
        description="USB",
        vid=1027,
        pid=24597,
        serial_number="test",
        manufacturer=None,
        product=None,
    )
    classic = SimpleNamespace(device="COM8", vid=None, pid=None)
    module = SimpleNamespace(comports=lambda: [usb, classic])
    monkeypatch.setattr(discovery.importlib, "import_module", lambda name: module)
    found = discovery._serial_candidates()
    assert [c.address for c in found] == ["COM7"]


@pytest.mark.asyncio
async def test_ble_scan_uses_advertisements_and_configured_timeout(monkeypatch):
    calls = []

    class Scanner:
        @staticmethod
        async def discover(**kwargs):
            calls.append(kwargs)
            return {
                "opaque": (
                    SimpleNamespace(address="opaque", name="Fallback"),
                    SimpleNamespace(
                        local_name="Sensor", service_uuids=["ABCD"], manufacturer_data={}, rssi=-60
                    ),
                )
            }

    monkeypatch.setattr(
        discovery.importlib, "import_module", lambda name: SimpleNamespace(BleakScanner=Scanner)
    )
    found = await discovery._ble_candidates(5)
    assert calls == [{"timeout": 5, "return_adv": True}]
    assert found[0].identifiers["service_uuids"] == ["abcd"]
