"""Tests for config.arc_watchdog config loading and validation."""

from pathlib import Path

import pytest

from config.arc_watchdog import load_arc_watchdog_config


def test_default_arc_watchdog_config_loads():
    config = load_arc_watchdog_config()

    assert config.config_version == "demo-001"
    assert config.version_label == "arc_watchdog_config.toml@demo-001"
    assert len(config.content_sha256) == 64
    assert set(config.raw["windows"]) == {"w1", "w2", "w3"}
    assert config.raw["fdr"]["method"] == "benjamini_hochberg"
    assert config.raw["fdr"]["alpha"] == 0.05


def test_rejects_non_bh_fdr_method(tmp_path: Path):
    config_path = tmp_path / "arc_watchdog_config.toml"
    config_path.write_text(
        """
config_version = "demo-bad"
config_role = "arc_watchdog"

[baseline]
window_duration_s = 120

[baseline.min_sample_count]
eeg = 1
hrv = 1
eda = 1
respiration = 1

[windows.w1]
label = "immediate"
start_s = 0
end_s = 30

[windows.w2]
label = "near_response"
start_s = 30
end_s = 120

[windows.w3]
label = "sustained_response"
start_s = 120
end_s = 300

[fdr]
method = "bonferroni"
alpha = 0.05
family_scope = "session"

[null_model]
method = "permutation"
permutation_count = 1000

[signal_components]
eeg = ["eeg_alpha_power"]
hrv = ["hrv_rmssd"]
eda = ["eda_mean"]
respiration = ["respiration_rate"]

[signal_availability_profile]
min_modalities_required = 2
require_echo_event = true
missing_signal_policy = "record_available_only"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fdr.method"):
        load_arc_watchdog_config(config_path)


def test_rejects_overlapping_windows(tmp_path: Path):
    config_path = tmp_path / "arc_watchdog_config.toml"
    config_path.write_text(
        """
config_version = "demo-bad"
config_role = "arc_watchdog"

[baseline]
window_duration_s = 120

[baseline.min_sample_count]
eeg = 1
hrv = 1
eda = 1
respiration = 1

[windows.w1]
label = "immediate"
start_s = 0
end_s = 30

[windows.w2]
label = "overlap"
start_s = 20
end_s = 120

[windows.w3]
label = "sustained_response"
start_s = 120
end_s = 300

[fdr]
method = "benjamini_hochberg"
alpha = 0.05
family_scope = "session"

[null_model]
method = "permutation"
permutation_count = 1000

[signal_components]
eeg = ["eeg_alpha_power"]
hrv = ["hrv_rmssd"]
eda = ["eda_mean"]
respiration = ["respiration_rate"]

[signal_availability_profile]
min_modalities_required = 2
require_echo_event = true
missing_signal_policy = "record_available_only"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ordered and non-overlapping"):
        load_arc_watchdog_config(config_path)


def test_rejects_missing_permutation_random_seed(tmp_path: Path):
    config_path = tmp_path / "arc_watchdog_config.toml"
    config_path.write_text(
        """
config_version = "demo-bad"
config_role = "arc_watchdog"

[baseline]
window_duration_s = 120

[baseline.min_sample_count]
eeg = 1
hrv = 1
eda = 1
respiration = 1

[windows.w1]
label = "immediate"
start_s = 0
end_s = 30

[windows.w2]
label = "near_response"
start_s = 30
end_s = 120

[windows.w3]
label = "sustained_response"
start_s = 120
end_s = 300

[fdr]
method = "benjamini_hochberg"
alpha = 0.05
family_scope = "session"

[null_model]
method = "permutation"
permutation_count = 1000

[signal_components]
eeg = ["eeg_alpha_power"]
hrv = ["hrv_rmssd"]
eda = ["eda_mean"]
respiration = ["respiration_rate"]

[signal_availability_profile]
min_modalities_required = 2
require_echo_event = true
missing_signal_policy = "record_available_only"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="random_seed"):
        load_arc_watchdog_config(config_path)
