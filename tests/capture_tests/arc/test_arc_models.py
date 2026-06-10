"""Spec-driven tests for batch/arc/models.py (arc-models.md).

Phase 5b — ARC in-memory value objects. Frozen dataclasses with
construction-time validation; no signal processing, no DB.
One test per R-xxx rule. Assertions derive from the spec text only.

NOTE (black-box): constructor keyword names below are inferred from the
spec's field references. Phase D resolves any signature mismatch in the
factory helpers only — assertion values are never adjusted.
"""

import pytest

from batch.arc.models import (
    APEXResponse,
    ARCConvergenceEvent,
    ARCWindowResponse,
    EchoAnchorEvent,
)
from tests.capture_tests.arc.support import (
    CONFIG_SHA256,
    CONFIG_VERSION,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


def _apex(window="w1", modality="hrv", signal_component="hrv_rmssd", **over):
    kwargs = dict(
        modality=modality,
        signal_component=signal_component,
        window=window,
        baseline_mean=10.0,
        baseline_std=2.0,
        observed_value=14.0,
        sample_count=500,
        z_score=2.0,
        p_value=0.02,
        effect_direction="increase",
        metadata={},
    )
    kwargs.update(over)
    return APEXResponse(**kwargs)


def _window_response(name="w1", start_s=0.0, end_s=30.0, responses=None, **over):
    if responses is None:
        responses = (_apex(window=name),)
    kwargs = dict(
        name=name,
        label="immediate",
        start_s=start_s,
        end_s=end_s,
        convergence_density=0.5,
        responses=tuple(responses),
    )
    kwargs.update(over)
    return ARCWindowResponse(**kwargs)


def _echo(**over):
    kwargs = dict(
        id=42,
        session_id=SESSION_ID,
        participant_id=PARTICIPANT_ID,
        site_id=SITE_ID,
        sponsor_id=SPONSOR_ID,
        event_type="manual_marker",
        source="manual_logging",
        actor_id=None,
        actor_role="therapist",
        zone_label="dose_administration",
        lsl_timestamp=1000.0,
    )
    kwargs.update(over)
    return EchoAnchorEvent(**kwargs)


def _event(**over):
    windows = over.pop(
        "windows",
        (
            _window_response("w1", 0.0, 30.0),
            _window_response("w2", 30.0, 120.0),
            _window_response("w3", 120.0, 300.0),
        ),
    )
    kwargs = dict(
        echo=_echo(),
        windows=windows,
        null_threshold=0.5,
        fdr_q_value=0.01,
        passed_fdr=True,
        temporal_alignment_score=0.9,
        sap_available_signals=("hrv.hrv_rmssd",),
        sap_participating_signals=("hrv.hrv_rmssd",),
        arc_config_version=CONFIG_VERSION,
        arc_config_sha256=CONFIG_SHA256,
    )
    kwargs.update(over)
    return ARCConvergenceEvent(**kwargs)


class TestAPEXResponseValidation:
    """arc-models.md — `APEXResponse` validation.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_negative_baseline_std_raises(self):
        with pytest.raises(ValueError):
            _apex(baseline_std=-0.1)

    @pytest.mark.parametrize("bad", [0, -1, -100])
    def test_r002_nonpositive_sample_count_raises(self, bad):
        with pytest.raises(ValueError):
            _apex(sample_count=bad)

    @pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0])
    def test_r003_p_value_out_of_range_raises(self, bad):
        with pytest.raises(ValueError):
            _apex(p_value=bad)

    def test_r004_arc_signal_id_format(self):
        resp = _apex(modality="eeg", signal_component="eeg_alpha_power")
        assert resp.arc_signal_id == "eeg.eeg_alpha_power"

    def test_r005_to_deviation_metric_nine_core_fields(self):
        metric = _apex().to_deviation_metric()
        for field in (
            "modality",
            "signal_component",
            "baseline_mean",
            "baseline_std",
            "observed_value",
            "sample_count",
            "z_score",
            "p_value",
            "effect_direction",
        ):
            assert field in metric

    def test_r006_metadata_key_only_when_nonempty(self):
        assert "metadata" not in _apex(metadata={}).to_deviation_metric()
        assert "metadata" in _apex(metadata={"reason": "x"}).to_deviation_metric()


class TestARCWindowResponseValidation:
    """arc-models.md — `ARCWindowResponse` validation.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r007_negative_start_s_raises(self):
        with pytest.raises(ValueError):
            _window_response(start_s=-1.0, end_s=30.0)

    def test_r008_end_not_after_start_raises(self):
        with pytest.raises(ValueError):
            _window_response(start_s=30.0, end_s=30.0)
        with pytest.raises(ValueError):
            _window_response(start_s=30.0, end_s=10.0)

    def test_r009_negative_convergence_density_raises(self):
        with pytest.raises(ValueError):
            _window_response(convergence_density=-0.1)

    def test_r010_response_window_must_match_name(self):
        mismatched = (_apex(window="w2"),)
        with pytest.raises(ValueError):
            _window_response(name="w1", responses=mismatched)

    def test_r011_participating_signals_sorted_unique(self):
        responses = (
            _apex(window="w1", modality="hrv", signal_component="hrv_rmssd"),
            _apex(window="w1", modality="eeg", signal_component="eeg_alpha_power"),
            _apex(window="w1", modality="hrv", signal_component="hrv_rmssd"),
        )
        wr = _window_response(name="w1", responses=responses)
        assert wr.participating_signals == ("eeg.eeg_alpha_power", "hrv.hrv_rmssd")


class TestARCConvergenceEventValidation:
    """arc-models.md — `ARCConvergenceEvent` validation.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r012_windows_must_be_ordered_w1_w2_w3(self):
        bad = (
            _window_response("w2", 30.0, 120.0),
            _window_response("w1", 0.0, 30.0),
            _window_response("w3", 120.0, 300.0),
        )
        with pytest.raises(ValueError):
            _event(windows=bad)

    @pytest.mark.parametrize("bad", [-0.01, 1.01])
    def test_r013_null_threshold_out_of_range_raises(self, bad):
        with pytest.raises(ValueError):
            _event(null_threshold=bad)

    @pytest.mark.parametrize("bad", [-0.01, 1.01])
    def test_r014_fdr_q_value_out_of_range_raises(self, bad):
        with pytest.raises(ValueError):
            _event(fdr_q_value=bad)

    def test_r015_passed_fdr_must_be_true(self):
        with pytest.raises(ValueError):
            _event(passed_fdr=False)

    @pytest.mark.parametrize("bad", [-0.01, 1.01])
    def test_r016_temporal_alignment_score_out_of_range_raises(self, bad):
        with pytest.raises(ValueError):
            _event(temporal_alignment_score=bad)

    def test_r016_temporal_alignment_score_none_allowed(self):
        # None is explicitly permitted by the spec.
        _event(temporal_alignment_score=None)

    def test_r017_empty_config_version_raises(self):
        with pytest.raises(ValueError):
            _event(arc_config_version="")

    @pytest.mark.parametrize("bad", ["a" * 63, "a" * 65, "", "abc"])
    def test_r018_config_sha256_must_be_64_chars(self, bad):
        with pytest.raises(ValueError):
            _event(arc_config_sha256=bad)


class TestSerialization:
    """arc-models.md — `to_event_composite_profile_row` serialization.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r019_row_includes_core_fields(self):
        row = _event().to_event_composite_profile_row()
        for field in (
            "echo_event_id",
            "deviation_metrics",
            "null_threshold",
            "fdr_q_value",
            "passed_fdr",
            "temporal_alignment_score",
            "sap_available_signals",
            "sap_participating_signals",
            "arc_config_version",
            "arc_config_sha256",
        ):
            assert field in row

    def test_r020_three_density_and_participating_columns(self):
        row = _event().to_event_composite_profile_row()
        for field in (
            "w1_convergence_density",
            "w2_convergence_density",
            "w3_convergence_density",
            "w1_participating_signals",
            "w2_participating_signals",
            "w3_participating_signals",
        ):
            assert field in row

    def test_r021_tenancy_fields_from_echo(self):
        row = _event().to_event_composite_profile_row()
        assert row["session_id"] == SESSION_ID
        assert row["participant_id"] == PARTICIPANT_ID
        assert row["site_id"] == SITE_ID
        assert row["sponsor_id"] == SPONSOR_ID
