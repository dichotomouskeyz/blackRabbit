"""Tests for config.arc_watchdog config loading and validation."""

from pathlib import Path

import pytest

from config.arc_watchdog import AnchorEventFilter, load_arc_watchdog_config

# Minimal valid TOML used as a base for negative tests — each test tweaks one field.
_MINIMAL_TOML = """
config_version = "test-001"
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
random_seed = 42

[signal_components]
eeg = ["eeg_alpha_power"]
hrv = ["hrv_rmssd"]
eda = ["eda_mean"]
respiration = ["respiration_rate"]

[signal_availability_profile]
min_modalities_required = 2
require_echo_event = true
missing_signal_policy = "record_available_only"

[[anchor_events.include]]
event_type = "manual_marker"
zone_label = "dose_administration"

[[anchor_events.include]]
event_type = "zone_enter"
zone_label = "arms_reach"
"""


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "arc_watchdog_config.toml"
    p.write_text(content, encoding="utf-8")
    return p


def test_default_arc_watchdog_config_loads():
    config = load_arc_watchdog_config()

    assert config.config_version == "demo-002"
    assert config.version_label == "arc_watchdog_config.toml@demo-002"
    assert len(config.content_sha256) == 64
    assert set(config.raw["windows"]) == {"w1", "w2", "w3"}
    assert config.raw["fdr"]["method"] == "benjamini_hochberg"
    assert config.raw["fdr"]["alpha"] == 0.05


def test_default_config_anchor_events_property():
    config = load_arc_watchdog_config()

    anchors = config.anchor_events
    assert isinstance(anchors, tuple)
    assert len(anchors) == 4
    assert AnchorEventFilter("manual_marker", "dose_administration") in anchors
    assert AnchorEventFilter("manual_marker", "participant_note") in anchors
    assert AnchorEventFilter("manual_marker", "environmental_note") in anchors
    assert AnchorEventFilter("zone_enter", "arms_reach") in anchors


def test_anchor_events_excludes_zone_exit_and_coarse_zones():
    config = load_arc_watchdog_config()

    anchor_pairs = {(a.event_type, a.zone_label) for a in config.anchor_events}
    assert ("zone_exit", "arms_reach") not in anchor_pairs
    assert ("zone_enter", "in_room") not in anchor_pairs
    assert ("zone_enter", "out_of_room") not in anchor_pairs


def test_rejects_non_bh_fdr_method(tmp_path: Path):
    content = _MINIMAL_TOML.replace('method = "benjamini_hochberg"', 'method = "bonferroni"')
    with pytest.raises(ValueError, match="fdr.method"):
        load_arc_watchdog_config(_write(tmp_path, content))


def test_rejects_overlapping_windows(tmp_path: Path):
    content = _MINIMAL_TOML.replace("start_s = 30\nend_s = 120", "start_s = 20\nend_s = 120")
    with pytest.raises(ValueError, match="ordered and non-overlapping"):
        load_arc_watchdog_config(_write(tmp_path, content))


def test_rejects_missing_permutation_random_seed(tmp_path: Path):
    content = _MINIMAL_TOML.replace("random_seed = 42\n", "")
    with pytest.raises(ValueError, match="random_seed"):
        load_arc_watchdog_config(_write(tmp_path, content))


def test_rejects_missing_anchor_events_section(tmp_path: Path):
    content = _MINIMAL_TOML.split("[[anchor_events")[0]
    with pytest.raises(ValueError, match="anchor_events"):
        load_arc_watchdog_config(_write(tmp_path, content))


def test_rejects_empty_anchor_events_include(tmp_path: Path):
    content = _MINIMAL_TOML.split("[[anchor_events")[0] + "\n[anchor_events]\ninclude = []\n"
    with pytest.raises(ValueError, match="anchor_events.include"):
        load_arc_watchdog_config(_write(tmp_path, content))


def test_rejects_invalid_anchor_event_type(tmp_path: Path):
    content = _MINIMAL_TOML.replace(
        'event_type = "manual_marker"\nzone_label = "dose_administration"',
        'event_type = "not_real"\nzone_label = "dose_administration"',
    )
    with pytest.raises(ValueError, match="event_type"):
        load_arc_watchdog_config(_write(tmp_path, content))


def test_rejects_invalid_anchor_zone_label(tmp_path: Path):
    content = _MINIMAL_TOML.replace(
        'event_type = "manual_marker"\nzone_label = "dose_administration"',
        'event_type = "manual_marker"\nzone_label = "not_real"',
    )
    with pytest.raises(ValueError, match="zone_label"):
        load_arc_watchdog_config(_write(tmp_path, content))
