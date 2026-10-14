"""HW-001..004, HW-006: declarative validation before hardware access."""

import json
from dataclasses import replace

import pytest

from capture.hardware.adapter import inspect_board, validate_config
from capture.hardware.configuration import BridgeConfig, DeviceBinding, load_config
from capture.hardware.errors import ValidationError
from capture.hardware.profiles import profile_from_dict, synthetic_profile
from config import settings


def test_profile_roundtrip_hash_and_synthetic_layout():
    profile = synthetic_profile()
    assert (
        profile.content_hash
        == profile_from_dict(json.loads(json.dumps(profile.to_dict()))).content_hash
    )
    config = BridgeConfig((DeviceBinding("bench", profile),))
    assert validate_config(config)["devices"][0]["source_kind"] == "simulated"
    assert [s.signal_type for s in profile.presets[0].signals] == ["EEG", "EDA", "PPG"]
    assert len(profile.presets[0].signals[0].rows) == 16


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(schema_version=2),
        lambda p: p.update(schema_version=True),
        lambda p: p.update(unrecognized=True),
        lambda p: p["presets"][0].update(sampling_rate=float("nan")),
        lambda p: p["presets"][0]["signals"][0].update(rows=[1, 1]),
        lambda p: p["presets"][0]["signals"][1].update(rows=[1]),
        lambda p: p["presets"][0]["signals"][1].update(labels=[]),
        lambda p: p["presets"][0]["signals"][1].update(scale=0),
        lambda p: p["presets"][0]["signals"][1].update(scale=float("inf")),
        lambda p: p["presets"][0]["signals"][1].update(units=["uS"]),
        lambda p: p["presets"][0]["signals"][1].update(signal_type="HRV", units=["ms"]),
        lambda p: p["presets"][0]["signals"][1].update(id="eeg"),
        lambda p: p["presets"][0].update(timestamp_origin="device_sample"),
    ],
)
def test_invalid_profiles_fail_before_any_adapter(mutation):
    data = json.loads(json.dumps(synthetic_profile().to_dict()))
    mutation(data)
    with pytest.raises(ValidationError):
        profile_from_dict(data)


@pytest.mark.parametrize("row", [0, 30, 32])
def test_reserved_and_out_of_range_rows_rejected(row):
    profile = synthetic_profile()
    preset = profile.presets[0]
    signal = replace(preset.signals[1], rows=(row,))
    profile = replace(profile, presets=(replace(preset, signals=(signal,)),))
    with pytest.raises(ValidationError):
        validate_config(BridgeConfig((DeviceBinding("bench", profile),)))


def test_inspection_reports_ambiguity_without_preparing(monkeypatch):
    from capture.hardware.adapter import BoardShim

    def forbidden(*args):
        pytest.fail("Inspection attempted hardware preparation")

    monkeypatch.setattr(BoardShim, "prepare_session", forbidden)
    result = inspect_board(-1)
    assert result["connection_verified"] is False
    assert {"eeg_channels", "ecg_channels", "emg_channels"} <= set(
        result["presets"][0]["ambiguous_rows"]["1"]
    )
    assert result["unresolved"]


def test_binding_uniqueness_and_closed_parameters():
    profile = synthetic_profile()
    with pytest.raises(ValidationError, match="Duplicate source_id"):
        BridgeConfig((DeviceBinding("same", profile), DeviceBinding("same", profile)))
    with pytest.raises(ValidationError):
        DeviceBinding("bench", profile, (("config_board", "arbitrary"),))
    with pytest.raises(ValidationError):
        DeviceBinding("bench", profile, (("ip_port", True),))
    preset = replace(profile.presets[0], timestamp_origin="unknown")
    physical = replace(profile, board_id=0, presets=(preset,))
    with pytest.raises(ValidationError, match="physical connection"):
        BridgeConfig(
            tuple(DeviceBinding(s, physical, (("serial_port", "COM8"),)) for s in ("left", "right"))
        )


def test_binding_paths_are_relative_to_config(tmp_path):
    (tmp_path / "profile.json").write_text(json.dumps(synthetic_profile().to_dict()))
    config_path = tmp_path / "setup.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bindings": [{"source_id": "bench", "profile": "profile.json", "parameters": {}}],
            }
        )
    )
    assert load_config(config_path).bindings[0].profile.id == "brainflow-synthetic"


def test_hardware_configuration_does_not_require_database(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    settings.validate_hardware()
    validate_config(BridgeConfig((DeviceBinding("bench", synthetic_profile()),)))
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.validate()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_hardware_defaults(value, monkeypatch):
    monkeypatch.setattr(settings, "HARDWARE_BLE_SCAN_SECONDS", value)
    with pytest.raises(RuntimeError):
        settings.validate_hardware()
