"""Session signal metadata row construction."""

from psycopg2.extras import Json

from config import settings

_RESPIRATION_DERIVED_SOURCES = frozenset({"rsa_derived"})


def _build_metadata_rows(
    session_id: str,
    site_id: str,
    sponsor_id: str,
    participant_id: str,
    capture_source: str,
    eeg_sensor_form: str | None,
    eeg_electrode_system: str | None,
    eeg_electrode_type: str | None,
    hrv_electrode_placement: str | None,
    hrv_electrode_type: str | None,
    eda_electrode_placement: str | None,
    eda_electrode_type: str | None,
    eda_skin_prep: str | None,
) -> list[dict]:
    """Return 4 dicts ready for _METADATA_INSERT, one per modality."""
    base = {
        "session_id": session_id,
        "site_id": site_id,
        "sponsor_id": sponsor_id,
        "participant_id": participant_id,
        "device_id": settings.DEVICE_ID,
        "capture_source": capture_source,
    }
    null = _null_metadata_fields()
    return [
        _eeg_metadata(base, null, eeg_sensor_form, eeg_electrode_system, eeg_electrode_type),
        _hrv_metadata(base, null, hrv_electrode_placement, hrv_electrode_type),
        _eda_metadata(base, null, eda_electrode_placement, eda_electrode_type, eda_skin_prep),
        _respiration_metadata(base, null),
    ]


def _null_metadata_fields() -> dict:
    return {
        "power_line_frequency": None,
        "sample_rate_hz": None,
        "software_filters": None,
        "eeg_reference": None,
        "eeg_sensor_form": None,
        "eeg_electrode_system": None,
        "eeg_electrode_type": None,
        "sampling_frequency": None,
        "eeg_channel_count": None,
        "eeg_channel_names": None,
        "cap_manufacturer": None,
        "cap_manufacturer_model_name": None,
        "hrv_signal_source": None,
        "hrv_electrode_placement": None,
        "hrv_electrode_type": None,
        "beat_detection_algorithm": None,
        "beat_detection_version": None,
        "eda_electrode_placement": None,
        "eda_electrode_type": None,
        "eda_skin_prep": None,
        "eda_signal_source": None,
        "eda_range_min_us": None,
        "eda_range_max_us": None,
        "respiration_source": None,
        "is_derived": None,
        "respiration_unit": None,
    }


def _eeg_metadata(
    base: dict,
    null: dict,
    eeg_sensor_form: str | None,
    eeg_electrode_system: str | None,
    eeg_electrode_type: str | None,
) -> dict:
    return {
        **base,
        **null,
        "modality": "eeg",
        "power_line_frequency": settings.POWER_LINE_FREQUENCY,
        "eeg_reference": settings.EEG_REFERENCE,
        "eeg_sensor_form": eeg_sensor_form or settings.EEG_SENSOR_FORM,
        "eeg_electrode_system": eeg_electrode_system or settings.EEG_ELECTRODE_SYSTEM,
        "eeg_electrode_type": eeg_electrode_type or settings.EEG_ELECTRODE_TYPE,
        "sampling_frequency": float(settings.SAMPLE_RATE_EEG),
        "eeg_channel_count": settings.EEG_CHANNEL_COUNT,
        "eeg_channel_names": Json(list(settings.EEG_CHANNEL_NAMES))
        if settings.EEG_CHANNEL_NAMES is not None
        else None,
        "cap_manufacturer": settings.CAP_MANUFACTURER,
        "cap_manufacturer_model_name": settings.CAP_MANUFACTURER_MODEL_NAME,
    }


def _hrv_metadata(
    base: dict,
    null: dict,
    hrv_electrode_placement: str | None,
    hrv_electrode_type: str | None,
) -> dict:
    return {
        **base,
        **null,
        "modality": "hrv",
        "sample_rate_hz": float(settings.SAMPLE_RATE_HRV),
        "hrv_signal_source": settings.HRV_SIGNAL_SOURCE,
        "hrv_electrode_placement": hrv_electrode_placement or settings.HRV_ELECTRODE_PLACEMENT,
        "hrv_electrode_type": hrv_electrode_type or settings.HRV_ELECTRODE_TYPE,
        "beat_detection_algorithm": settings.BEAT_DETECTION_ALGORITHM,
        "beat_detection_version": settings.BEAT_DETECTION_VERSION,
    }


def _eda_metadata(
    base: dict,
    null: dict,
    eda_electrode_placement: str | None,
    eda_electrode_type: str | None,
    eda_skin_prep: str | None,
) -> dict:
    return {
        **base,
        **null,
        "modality": "eda",
        "sample_rate_hz": float(settings.SAMPLE_RATE_EDA),
        "eda_electrode_placement": eda_electrode_placement,
        "eda_electrode_type": eda_electrode_type,
        "eda_skin_prep": eda_skin_prep,
        "eda_signal_source": settings.EDA_SIGNAL_SOURCE,
        "eda_range_min_us": settings.EDA_RANGE_MIN_US,
        "eda_range_max_us": settings.EDA_RANGE_MAX_US,
    }


def _respiration_metadata(base: dict, null: dict) -> dict:
    return {
        **base,
        **null,
        "modality": "respiration",
        "sample_rate_hz": float(settings.SAMPLE_RATE_RESPIRATION),
        "respiration_source": settings.RESPIRATION_SOURCE,
        "is_derived": settings.RESPIRATION_SOURCE in _RESPIRATION_DERIVED_SOURCES,
        "respiration_unit": settings.RESPIRATION_UNIT,
    }
