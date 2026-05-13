"""Per-modality row builders for LSL samples."""

from capture.forwarder.models import SessionConfig
from config import settings


def _build_eeg_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "channel_id": f"ch_{ch}",
            "voltage": voltage,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
        for ch, voltage in enumerate(sample)
    ]


def _build_hrv_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    rr_ms = sample[0]
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "rr_interval_ms": rr_ms,
            "heart_rate_bpm": 60000.0 / rr_ms if rr_ms > 0 else None,
            "beat_quality": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]


def _build_eda_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    conductance = sample[0]
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "raw_conductance_us": conductance,
            "conductance_us": conductance,
            "signal_quality": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]


def _build_respiration_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    amplitude = sample[0]
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "raw_amplitude": amplitude,
            "processed_amplitude": amplitude,
            "breath_phase": None,
            "breaths_per_min": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]
