"""Spec-driven tests for config/settings.py (settings.md).

Phase 2 — runtime configuration loader. All unit tests; no DB.
One test per R-xxx rule. Assertions derive from the spec text only.

Per the spec's Risks section, env changes after import do not update
module-level globals, so `validate()` tests patch `config.settings`
attributes directly and derived-value tests reload the module.
"""

import importlib

import pytest

import config.settings as settings
from config.settings import _get_optional, _get_optional_csv, _require

_VALID_UUID = "abcdabcd-0000-4000-8000-000000000001"


class TestRequire:
    """settings.md — `_require`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_unset_raises(self, monkeypatch):
        monkeypatch.delenv("SOME_REQUIRED_KEY", raising=False)
        with pytest.raises(RuntimeError):
            _require("SOME_REQUIRED_KEY")

    def test_r002_empty_string_raises(self, monkeypatch):
        monkeypatch.setenv("SOME_REQUIRED_KEY", "")
        with pytest.raises(RuntimeError):
            _require("SOME_REQUIRED_KEY")

    def test_r003_returns_value(self, monkeypatch):
        monkeypatch.setenv("SOME_REQUIRED_KEY", "value-x")
        assert _require("SOME_REQUIRED_KEY") == "value-x"


class TestOptional:
    """settings.md — `_get_optional` / `_get_optional_csv`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r004_optional_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPT_KEY", raising=False)
        assert _get_optional("OPT_KEY") is None

    def test_r005_optional_empty_returns_none(self, monkeypatch):
        monkeypatch.setenv("OPT_KEY", "")
        assert _get_optional("OPT_KEY") is None

    def test_r006_csv_unset_or_empty_returns_none(self, monkeypatch):
        monkeypatch.delenv("CSV_KEY", raising=False)
        assert _get_optional_csv("CSV_KEY") is None
        monkeypatch.setenv("CSV_KEY", "")
        assert _get_optional_csv("CSV_KEY") is None

    def test_r007_csv_whitespace_only_returns_none(self, monkeypatch):
        monkeypatch.setenv("CSV_KEY", "   ")
        assert _get_optional_csv("CSV_KEY") is None
        monkeypatch.setenv("CSV_KEY", " , , ")
        assert _get_optional_csv("CSV_KEY") is None

    def test_r008_csv_returns_stripped_nonempty_tuple(self, monkeypatch):
        monkeypatch.setenv("CSV_KEY", " a , b ,c ")
        assert _get_optional_csv("CSV_KEY") == ("a", "b", "c")


@pytest.fixture
def valid_settings(monkeypatch):
    """Patch all validation-relevant settings to known-good values."""
    good = {
        "DATABASE_URL": "postgresql://u:p@localhost:5432/db",
        "DEVICE_ID": _VALID_UUID,
        "CAPTURE_SOURCE": "simulated",
        "HRV_SIGNAL_SOURCE": "ecg",
        "EDA_SIGNAL_SOURCE": "combined",
        "RESPIRATION_SOURCE": "belt_direct",
        "SAMPLE_RATE_EEG": 256,
        "SAMPLE_RATE_HRV": 4,
        "SAMPLE_RATE_EDA": 32,
        "SAMPLE_RATE_RESPIRATION": 32,
        "EEG_CHANNEL_COUNT": 4,
        "EEG_CHANNEL_NAMES": None,
    }
    for key, value in good.items():
        monkeypatch.setattr(settings, key, value, raising=False)
    return monkeypatch


class TestValidate:
    """settings.md — `validate()`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r009_empty_database_url_raises(self, valid_settings):
        valid_settings.setattr(settings, "DATABASE_URL", "", raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r010_numeric_out_of_range_raises(self, valid_settings):
        valid_settings.setattr(settings, "SAMPLE_RATE_EEG", 0, raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()
        valid_settings.setattr(settings, "SAMPLE_RATE_EEG", 100000, raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r011_invalid_device_id_raises(self, valid_settings):
        valid_settings.setattr(settings, "DEVICE_ID", "not-a-uuid", raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r012_invalid_hrv_signal_source_raises(self, valid_settings):
        valid_settings.setattr(settings, "HRV_SIGNAL_SOURCE", "bogus", raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r013_invalid_eda_signal_source_raises(self, valid_settings):
        valid_settings.setattr(settings, "EDA_SIGNAL_SOURCE", "bogus", raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r014_invalid_respiration_source_raises(self, valid_settings):
        valid_settings.setattr(settings, "RESPIRATION_SOURCE", "bogus", raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r015_invalid_capture_mode_raises(self, valid_settings):
        # Spec calls this CAPTURE_MODE; the implementation's setting is
        # CAPTURE_SOURCE (same simulated|hardware semantics) — naming drift.
        valid_settings.setattr(settings, "CAPTURE_SOURCE", "bogus", raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r016_channel_names_count_mismatch_raises(self, valid_settings):
        valid_settings.setattr(settings, "EEG_CHANNEL_COUNT", 4, raising=False)
        valid_settings.setattr(settings, "EEG_CHANNEL_NAMES", ("ch_0", "ch_1"), raising=False)
        with pytest.raises(RuntimeError):
            settings.validate()

    def test_r017_multiple_failures_single_error_all_messages(self, valid_settings):
        valid_settings.setattr(settings, "DEVICE_ID", "not-a-uuid", raising=False)
        valid_settings.setattr(settings, "HRV_SIGNAL_SOURCE", "bogus", raising=False)
        with pytest.raises(RuntimeError) as exc:
            settings.validate()
        message = str(exc.value)
        assert "DEVICE_ID" in message
        assert "HRV_SIGNAL_SOURCE" in message

    def test_r018_all_valid_does_not_raise(self, valid_settings):
        settings.validate()


@pytest.fixture
def reload_settings():
    """Reload config.settings under controlled env, restoring afterwards."""
    yield importlib.reload
    importlib.reload(settings)


class TestDerivedValues:
    """settings.md — derived values.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    # NOTE (Phase D finding): the spec names this setting CAPTURE_MODE; the
    # implementation uses CAPTURE_SOURCE with identical simulated|hardware
    # semantics. Tests below target the real setting name.

    def test_r019_simulation_mode_follows_capture_mode(self, monkeypatch, reload_settings):
        monkeypatch.setenv("CAPTURE_SOURCE", "simulated")
        monkeypatch.delenv("SIMULATION_MODE", raising=False)
        reloaded = reload_settings(settings)
        assert reloaded.SIMULATION_MODE is True

        monkeypatch.setenv("CAPTURE_SOURCE", "hardware")
        reloaded = reload_settings(settings)
        assert reloaded.SIMULATION_MODE is False

    def test_r020_capture_mode_defaults_simulated(self, monkeypatch, reload_settings):
        monkeypatch.delenv("CAPTURE_SOURCE", raising=False)
        monkeypatch.delenv("SIMULATION_MODE", raising=False)
        reloaded = reload_settings(settings)
        assert reloaded.CAPTURE_SOURCE == "simulated"

    def test_r021_simulation_false_defaults_capture_hardware(self, monkeypatch, reload_settings):
        monkeypatch.delenv("CAPTURE_SOURCE", raising=False)
        monkeypatch.setenv("SIMULATION_MODE", "false")
        reloaded = reload_settings(settings)
        assert reloaded.CAPTURE_SOURCE == "hardware"
