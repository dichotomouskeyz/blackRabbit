"""Tests for the canonical ARC convergence event object."""

import pytest

from batch.arc_models import (
    APEXResponse,
    ARCConvergenceEvent,
    ARCWindowResponse,
    EchoAnchorEvent,
)

_SHA = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _echo() -> EchoAnchorEvent:
    return EchoAnchorEvent(
        id=42,
        session_id="11111111-1111-1111-1111-111111111111",
        participant_id="22222222-2222-2222-2222-222222222222",
        site_id="33333333-3333-3333-3333-333333333333",
        sponsor_id="44444444-4444-4444-4444-444444444444",
        event_type="zone_enter",
        source="manual_logging",
        actor_id="therapist_01",
        actor_role="therapist",
        zone_label="arms_reach",
        lsl_timestamp=12345.67,
    )


def _event() -> ARCConvergenceEvent:
    hrv = APEXResponse(
        modality="hrv",
        signal_component="hrv_rmssd",
        window="w1",
        baseline_mean=42.0,
        baseline_std=3.5,
        observed_value=31.0,
        sample_count=30,
        z_score=-3.14,
        p_value=0.002,
        effect_direction="decrease",
    )
    eda = APEXResponse(
        modality="eda",
        signal_component="eda_phasic_amplitude",
        window="w2",
        baseline_mean=0.2,
        baseline_std=0.05,
        observed_value=0.41,
        sample_count=120,
        z_score=4.2,
        p_value=0.001,
        effect_direction="increase",
    )
    return ARCConvergenceEvent(
        echo=_echo(),
        windows=(
            ARCWindowResponse(
                name="w1",
                label="immediate",
                start_s=0.0,
                end_s=30.0,
                convergence_density=0.33,
                responses=(hrv,),
            ),
            ARCWindowResponse(
                name="w2",
                label="near_response",
                start_s=30.0,
                end_s=120.0,
                convergence_density=0.50,
                responses=(eda,),
            ),
            ARCWindowResponse(
                name="w3",
                label="sustained_response",
                start_s=120.0,
                end_s=300.0,
                convergence_density=0.0,
                responses=(),
            ),
        ),
        null_threshold=0.95,
        fdr_q_value=0.004,
        passed_fdr=True,
        sap_available_signals=(
            "hrv.hrv_rmssd",
            "eda.eda_phasic_amplitude",
            "eeg.eeg_alpha_power",
        ),
        sap_participating_signals=("hrv.hrv_rmssd", "eda.eda_phasic_amplitude"),
        temporal_alignment_score=0.88,
        arc_config_version="arc_watchdog_config.toml@demo-001",
        arc_config_sha256=_SHA,
    )


class TestARCConvergenceEvent:
    def test_serializes_to_event_composite_profile_row(self):
        row = _event().to_event_composite_profile_row()

        assert row["session_id"] == "11111111-1111-1111-1111-111111111111"
        assert row["echo_event_id"] == 42
        assert row["w1_convergence_density"] == pytest.approx(0.33)
        assert row["w2_convergence_density"] == pytest.approx(0.50)
        assert row["w3_convergence_density"] == pytest.approx(0.0)
        assert row["w1_participating_signals"] == ["hrv.hrv_rmssd"]
        assert row["w2_participating_signals"] == ["eda.eda_phasic_amplitude"]
        assert row["w3_participating_signals"] == []
        assert row["deviation_metrics"]["w1"]["hrv.hrv_rmssd"]["z_score"] == pytest.approx(
            -3.14
        )
        assert row["deviation_metrics"]["w2"]["eda.eda_phasic_amplitude"][
            "effect_direction"
        ] == "increase"
        assert row["arc_config_sha256"] == _SHA

    def test_requires_ordered_three_window_arc_shape(self):
        event = _event()

        with pytest.raises(ValueError, match="ordered as w1, w2, w3"):
            ARCConvergenceEvent(
                echo=event.echo,
                windows=(event.windows[1], event.windows[0], event.windows[2]),
                null_threshold=event.null_threshold,
                fdr_q_value=event.fdr_q_value,
                passed_fdr=True,
                sap_available_signals=event.sap_available_signals,
                sap_participating_signals=event.sap_participating_signals,
                arc_config_version=event.arc_config_version,
                arc_config_sha256=event.arc_config_sha256,
            )

    def test_rejects_non_fdr_passing_event_for_durable_profile(self):
        event = _event()

        with pytest.raises(ValueError, match="FDR-passing"):
            ARCConvergenceEvent(
                echo=event.echo,
                windows=event.windows,
                null_threshold=event.null_threshold,
                fdr_q_value=0.50,
                passed_fdr=False,
                sap_available_signals=event.sap_available_signals,
                sap_participating_signals=event.sap_participating_signals,
                arc_config_version=event.arc_config_version,
                arc_config_sha256=event.arc_config_sha256,
            )

    def test_response_must_belong_to_window(self):
        response = APEXResponse(
            modality="eeg",
            signal_component="eeg_alpha_power",
            window="w2",
            baseline_mean=1.0,
            baseline_std=0.1,
            observed_value=1.4,
            sample_count=512,
            z_score=4.0,
            p_value=0.001,
        )

        with pytest.raises(ValueError, match="belong to the window"):
            ARCWindowResponse(
                name="w1",
                label="immediate",
                start_s=0.0,
                end_s=30.0,
                convergence_density=1.0,
                responses=(response,),
            )
