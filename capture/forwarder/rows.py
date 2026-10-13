"""Per-modality row builders for LSL samples."""

from capture.forwarder.models import SessionConfig
from config import settings


def build_eeg_rows(
    sample: list[float],
    cfg: SessionConfig,
    lsl_ts: float,
    sample_index: int,
) -> list[dict]:
    channel_names = (
        cfg.eeg_channel_names
        if cfg.eeg_channel_names is not None
        else tuple(f"ch_{ch}" for ch in range(len(sample)))
    )
    if len(channel_names) != len(sample):
        raise ValueError(
            "EEG channel name count must match sample width "
            f"({len(channel_names)} != {len(sample)})"
        )
    return [
        {
            "session_id": cfg.session_id,
            "participant_id": cfg.participant_id,
            "site_id": cfg.site_id,
            "sponsor_id": cfg.sponsor_id,
            "device_id": settings.DEVICE_ID,
            "channel_id": channel_id,
            "voltage": voltage,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
        for channel_id, voltage in zip(channel_names, sample)
    ]


def build_hrv_rows(
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


def build_eda_rows(
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
            # Phase 5 placeholder: this is still a pass-through copy of the raw value.
            "conductance_us": conductance,
            "signal_quality": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]


def build_respiration_rows(
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
            # Phase 5 placeholder: this is still a pass-through copy of the raw value.
            "processed_amplitude": amplitude,
            "breath_phase": None,
            "breaths_per_min": None,
            "lsl_timestamp": lsl_ts,
            "sample_index": sample_index,
        }
    ]


_build_eeg_rows = build_eeg_rows
_build_hrv_rows = build_hrv_rows
_build_eda_rows = build_eda_rows
_build_respiration_rows = build_respiration_rows
