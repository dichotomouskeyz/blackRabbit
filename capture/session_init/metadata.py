"""Session signal metadata row construction.

One `SignalMetadataRow` dataclass mirrors the session_signal_metadata insert
columns, replacing the old null-dict "shadow schema": adding a column now
means adding one dataclass field (constructed rows fail loudly on typos via
TypeError), and each modality builder states only the fields it actually sets.
`_build_metadata_rows` keeps its kwargs signature and dict output — they are
the spec-pinned contract.
"""

from dataclasses import dataclass, fields

from psycopg2.extras import Json

from config import settings

_RESPIRATION_DERIVED_SOURCES = frozenset({"rsa_derived"})


@dataclass
class SignalMetadataRow:
    """One session_signal_metadata row; fields mirror _METADATA_INSERT params."""

    # Identity (required for every modality)
    session_id: str
    site_id: str
    sponsor_id: str
    participant_id: str
    device_id: str
    capture_source: str
    modality: str

    # Shared signal fields
    power_line_frequency: float | None = None
    sample_rate_hz: float | None = None
    software_filters: object | None = None

    # EEG
    eeg_reference: str | None = None
    eeg_sensor_form: str | None = None
    eeg_electrode_system: str | None = None
    eeg_electrode_type: str | None = None
    sampling_frequency: float | None = None
    eeg_channel_count: int | None = None
    eeg_channel_names: object | None = None
    cap_manufacturer: str | None = None
    cap_manufacturer_model_name: str | None = None

    # HRV
    hrv_signal_source: str | None = None
    hrv_electrode_placement: str | None = None
    hrv_electrode_type: str | None = None
    beat_detection_algorithm: str | None = None
    beat_detection_version: str | None = None

    # EDA
    eda_electrode_placement: str | None = None
    eda_electrode_type: str | None = None
    eda_skin_prep: str | None = None
    eda_signal_source: str | None = None
    eda_range_min_us: float | None = None
    eda_range_max_us: float | None = None

    # Respiration
    respiration_source: str | None = None
    is_derived: bool | None = None
    respiration_unit: str | None = None

    def as_row(self) -> dict:
        # Shallow per-field read (not dataclasses.asdict) so psycopg2 Json
        # wrapper values pass through untouched.
        return {f.name: getattr(self, f.name) for f in fields(self)}


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
    identity = {
        "session_id": session_id,
        "site_id": site_id,
        "sponsor_id": sponsor_id,
        "participant_id": participant_id,
        "device_id": settings.DEVICE_ID,
        "capture_source": capture_source,
    }
    rows = [
        _eeg_metadata(identity, eeg_sensor_form, eeg_electrode_system, eeg_electrode_type),
        _hrv_metadata(identity, hrv_electrode_placement, hrv_electrode_type),
        _eda_metadata(identity, eda_electrode_placement, eda_electrode_type, eda_skin_prep),
        _respiration_metadata(identity),
    ]
    return [row.as_row() for row in rows]


def _eeg_metadata(
    identity: dict,
    eeg_sensor_form: str | None,
    eeg_electrode_system: str | None,
    eeg_electrode_type: str | None,
) -> SignalMetadataRow:
    return SignalMetadataRow(
        **identity,
        modality="eeg",
        power_line_frequency=settings.POWER_LINE_FREQUENCY,
        eeg_reference=settings.EEG_REFERENCE,
        eeg_sensor_form=eeg_sensor_form or settings.EEG_SENSOR_FORM,
        eeg_electrode_system=eeg_electrode_system or settings.EEG_ELECTRODE_SYSTEM,
        eeg_electrode_type=eeg_electrode_type or settings.EEG_ELECTRODE_TYPE,
        sampling_frequency=float(settings.SAMPLE_RATE_EEG),
        eeg_channel_count=settings.EEG_CHANNEL_COUNT,
        eeg_channel_names=Json(list(settings.EEG_CHANNEL_NAMES))
        if settings.EEG_CHANNEL_NAMES is not None
        else None,
        cap_manufacturer=settings.CAP_MANUFACTURER,
        cap_manufacturer_model_name=settings.CAP_MANUFACTURER_MODEL_NAME,
    )


def _hrv_metadata(
    identity: dict,
    hrv_electrode_placement: str | None,
    hrv_electrode_type: str | None,
) -> SignalMetadataRow:
    return SignalMetadataRow(
        **identity,
        modality="hrv",
        sample_rate_hz=float(settings.SAMPLE_RATE_HRV),
        hrv_signal_source=settings.HRV_SIGNAL_SOURCE,
        hrv_electrode_placement=hrv_electrode_placement or settings.HRV_ELECTRODE_PLACEMENT,
        hrv_electrode_type=hrv_electrode_type or settings.HRV_ELECTRODE_TYPE,
        beat_detection_algorithm=settings.BEAT_DETECTION_ALGORITHM,
        beat_detection_version=settings.BEAT_DETECTION_VERSION,
    )


def _eda_metadata(
    identity: dict,
    eda_electrode_placement: str | None,
    eda_electrode_type: str | None,
    eda_skin_prep: str | None,
) -> SignalMetadataRow:
    return SignalMetadataRow(
        **identity,
        modality="eda",
        sample_rate_hz=float(settings.SAMPLE_RATE_EDA),
        eda_electrode_placement=eda_electrode_placement,
        eda_electrode_type=eda_electrode_type,
        eda_skin_prep=eda_skin_prep,
        eda_signal_source=settings.EDA_SIGNAL_SOURCE,
        eda_range_min_us=settings.EDA_RANGE_MIN_US,
        eda_range_max_us=settings.EDA_RANGE_MAX_US,
    )


def _respiration_metadata(identity: dict) -> SignalMetadataRow:
    return SignalMetadataRow(
        **identity,
        modality="respiration",
        sample_rate_hz=float(settings.SAMPLE_RATE_RESPIRATION),
        respiration_source=settings.RESPIRATION_SOURCE,
        is_derived=settings.RESPIRATION_SOURCE in _RESPIRATION_DERIVED_SOURCES,
        respiration_unit=settings.RESPIRATION_UNIT,
    )
