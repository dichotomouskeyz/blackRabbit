"""Consensai 1a — Session initializer.

Creates a row in the sessions table, transitions status to 'active', then
writes exactly four rows to session_signal_metadata (one per modality in
the order eeg → hrv → eda → respiration) inside the same transaction.

Prints the session UUID to stdout so it can be captured and passed
directly to lsl_forwarder.py.

Usage:
    python -m capture.session_init \\
        --compound          psilocybin \\
        --site-id           <uuid> \\
        --sponsor-id        <uuid> \\
        --participant-id    <uuid> \\
        [--compound-dose 25.0] \\
        [--compound-dose-unit mg] \\
        [--protocol-arm high_dose_25mg] \\
        [--room-id <uuid>] \\
        [--electrode-placement palmar] \\
        [--electrode-type ag_agcl] \\
        [--skin-prep cleaned]

Typical workflow:
    SESSION_ID=$(python -m capture.session_init --compound psilocybin ...)
    python -m capture.lsl_forwarder --session-id $SESSION_ID ...
"""

import argparse
import uuid

import psycopg2

from capture.logger import get_logger, set_session_id
from config import settings

settings.validate()

log = get_logger("session_init")

VALID_COMPOUNDS = (
    "psilocybin",
    "psilocin",
    "lsd",
    "dmt",
    "5meo_dmt",
    "ibogaine",
    "ibogaine_hcl",
    "mdma",
)
VALID_DOSE_UNITS = ("mg", "ug", "µg", "mg/kg", "ug/kg", "µg/kg")

# Columns must match session_signal_metadata exactly (migration 019).
_METADATA_INSERT = """
    INSERT INTO session_signal_metadata (
        session_id, site_id, sponsor_id, participant_id, device_id,
        modality,
        power_line_frequency, sample_rate_hz, software_filters,
        eeg_reference, sampling_frequency, eeg_channel_count,
        cap_manufacturer, cap_manufacturer_model_name,
        hrv_signal_source, beat_detection_algorithm, beat_detection_version,
        electrode_placement, electrode_type, skin_prep,
        eda_signal_source, eda_range_min_us, eda_range_max_us,
        respiration_source, is_derived, respiration_unit
    ) VALUES (
        %(session_id)s, %(site_id)s, %(sponsor_id)s, %(participant_id)s, %(device_id)s,
        %(modality)s,
        %(power_line_frequency)s, %(sample_rate_hz)s, %(software_filters)s,
        %(eeg_reference)s, %(sampling_frequency)s, %(eeg_channel_count)s,
        %(cap_manufacturer)s, %(cap_manufacturer_model_name)s,
        %(hrv_signal_source)s, %(beat_detection_algorithm)s, %(beat_detection_version)s,
        %(electrode_placement)s, %(electrode_type)s, %(skin_prep)s,
        %(eda_signal_source)s, %(eda_range_min_us)s, %(eda_range_max_us)s,
        %(respiration_source)s, %(is_derived)s, %(respiration_unit)s
    )
"""


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize a Consensai recording session")
    p.add_argument("--compound", required=True, choices=VALID_COMPOUNDS)
    p.add_argument("--site-id", required=True, type=_parse_uuid, help="Site UUID")
    p.add_argument("--sponsor-id", required=True, type=_parse_uuid, help="Sponsor UUID")
    p.add_argument(
        "--participant-id",
        required=True,
        type=_parse_uuid,
        help="Pseudonymous participant UUID",
    )
    p.add_argument("--compound-dose", type=float, default=None)
    p.add_argument("--compound-dose-unit", choices=VALID_DOSE_UNITS, default=None)
    p.add_argument("--protocol-arm", default=None)
    p.add_argument("--room-id", type=_parse_uuid, default=None, help="Room UUID")
    # EDA electrode setup — session-specific, not in settings
    p.add_argument(
        "--electrode-placement",
        choices=("palmar", "thenar", "plantar", "other"),
        default=None,
        help="EDA electrode placement site",
    )
    p.add_argument(
        "--electrode-type",
        choices=("ag_agcl", "dry", "other"),
        default=None,
        help="EDA electrode material",
    )
    p.add_argument(
        "--skin-prep",
        choices=("cleaned", "abraded", "cleaned_and_abraded", "none", "unknown"),
        default=None,
        help="Skin preparation before EDA electrode placement",
    )
    return p.parse_args()


def _build_metadata_rows(
    session_id: str,
    site_id: str,
    sponsor_id: str,
    participant_id: str,
    electrode_placement: str | None,
    electrode_type: str | None,
    skin_prep: str | None,
) -> list[dict]:
    """Return 4 dicts ready for _METADATA_INSERT, one per modality."""
    base = {
        "session_id": session_id,
        "site_id": site_id,
        "sponsor_id": sponsor_id,
        "participant_id": participant_id,
        "device_id": settings.DEVICE_ID,
    }
    null = {
        "power_line_frequency": None,
        "sample_rate_hz": None,
        "software_filters": None,
        "eeg_reference": None,
        "sampling_frequency": None,
        "eeg_channel_count": None,
        "cap_manufacturer": None,
        "cap_manufacturer_model_name": None,
        "hrv_signal_source": None,
        "beat_detection_algorithm": None,
        "beat_detection_version": None,
        "electrode_placement": None,
        "electrode_type": None,
        "skin_prep": None,
        "eda_signal_source": None,
        "eda_range_min_us": None,
        "eda_range_max_us": None,
        "respiration_source": None,
        "is_derived": None,
        "respiration_unit": None,
    }

    eeg = {
        **base,
        **null,
        "modality": "eeg",
        "power_line_frequency": settings.POWER_LINE_FREQUENCY,
        "eeg_reference": settings.EEG_REFERENCE,
        "sampling_frequency": float(settings.SAMPLE_RATE_EEG),
        "eeg_channel_count": settings.EEG_CHANNEL_COUNT,
        "cap_manufacturer": settings.CAP_MANUFACTURER,
        "cap_manufacturer_model_name": settings.CAP_MANUFACTURER_MODEL_NAME,
    }

    hrv = {
        **base,
        **null,
        "modality": "hrv",
        "sample_rate_hz": float(settings.SAMPLE_RATE_HRV),
        "hrv_signal_source": settings.HRV_SIGNAL_SOURCE,
        "beat_detection_algorithm": settings.BEAT_DETECTION_ALGORITHM,
        "beat_detection_version": settings.BEAT_DETECTION_VERSION,
    }

    eda = {
        **base,
        **null,
        "modality": "eda",
        "sample_rate_hz": float(settings.SAMPLE_RATE_EDA),
        "electrode_placement": electrode_placement,
        "electrode_type": electrode_type,
        "skin_prep": skin_prep,
        "eda_signal_source": settings.EDA_SIGNAL_SOURCE,
        "eda_range_min_us": settings.EDA_RANGE_MIN_US,
        "eda_range_max_us": settings.EDA_RANGE_MAX_US,
    }

    respiration = {
        **base,
        **null,
        "modality": "respiration",
        "sample_rate_hz": float(settings.SAMPLE_RATE_RESPIRATION),
        "respiration_source": settings.RESPIRATION_SOURCE,
        "is_derived": settings.RESPIRATION_SOURCE == "rsa_derived",
        "respiration_unit": settings.RESPIRATION_UNIT,
    }

    return [eeg, hrv, eda, respiration]


def create_session(
    compound: str,
    site_id: str,
    sponsor_id: str,
    participant_id: str,
    compound_dose: float | None = None,
    compound_dose_unit: str | None = None,
    protocol_arm: str | None = None,
    room_id: str | None = None,
    electrode_placement: str | None = None,
    electrode_type: str | None = None,
    skin_prep: str | None = None,
) -> str:
    """Insert sessions anchor row, write 4 signal metadata rows, return session UUID.

    All writes occur in a single transaction — if any metadata insert fails,
    the entire session creation is rolled back.
    """
    session_id = str(uuid.uuid4())

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()

        # 1. Anchor row
        cur.execute(
            """
            INSERT INTO sessions (
                id, site_id, sponsor_id, participant_id,
                compound, compound_dose, compound_dose_unit,
                protocol_arm, room_id,
                status, started_at
            ) VALUES (
                %(id)s, %(site_id)s, %(sponsor_id)s, %(participant_id)s,
                %(compound)s, %(compound_dose)s, %(compound_dose_unit)s,
                %(protocol_arm)s, %(room_id)s,
                'initializing', NOW()
            )
            """,
            {
                "id": session_id,
                "site_id": site_id,
                "sponsor_id": sponsor_id,
                "participant_id": participant_id,
                "compound": compound,
                "compound_dose": compound_dose,
                "compound_dose_unit": compound_dose_unit,
                "protocol_arm": protocol_arm,
                "room_id": room_id,
            },
        )

        # 2. Transition to active — forwarder starts writing
        cur.execute(
            "UPDATE sessions SET status = 'active' WHERE id = %s",
            (session_id,),
        )

        # 3. One metadata row per modality, in canonical order
        for row in _build_metadata_rows(
            session_id=session_id,
            site_id=site_id,
            sponsor_id=sponsor_id,
            participant_id=participant_id,
            electrode_placement=electrode_placement,
            electrode_type=electrode_type,
            skin_prep=skin_prep,
        ):
            cur.execute(_METADATA_INSERT, row)

        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return session_id


def main() -> None:
    args = _parse_args()

    log.info(
        "creating session",
        extra={
            "compound": args.compound,
            "site_id": args.site_id,
            "sponsor_id": args.sponsor_id,
            "simulation_mode": settings.SIMULATION_MODE,
        },
    )

    session_id = create_session(
        compound=args.compound,
        site_id=args.site_id,
        sponsor_id=args.sponsor_id,
        participant_id=args.participant_id,
        compound_dose=args.compound_dose,
        compound_dose_unit=args.compound_dose_unit,
        protocol_arm=args.protocol_arm,
        room_id=args.room_id,
        electrode_placement=args.electrode_placement,
        electrode_type=args.electrode_type,
        skin_prep=args.skin_prep,
    )

    set_session_id(session_id)
    log.info("session created", extra={"session_id": session_id, "status": "active"})

    # Print UUID alone on stdout so callers can capture it with $()
    print(session_id)


if __name__ == "__main__":
    main()
