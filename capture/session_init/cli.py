"""Command-line interface for session initialization."""

import argparse
import uuid

from capture.logger import get_logger, set_session_id
from capture.session_init.constants import VALID_COMPOUNDS, VALID_DOSE_UNITS
from capture.session_init.workflow import create_session
from config import settings

log = get_logger("session_init")


def _parse_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize a untitledplatform_1a recording session")
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
    p.add_argument(
        "--capture-source",
        choices=("simulated", "hardware"),
        default=settings.CAPTURE_SOURCE,
        help="Persisted capture source for the session (default: %(default)s)",
    )
    p.add_argument("--protocol-arm", default=None)
    p.add_argument("--room-id", type=_parse_uuid, default=None, help="Room UUID")
    p.add_argument(
        "--eeg-sensor-form",
        choices=("cap", "individual_electrodes", "dry_headset", "other", "unknown"),
        default=None,
        help="EEG physical collection form",
    )
    p.add_argument(
        "--eeg-electrode-system",
        choices=("ten_twenty", "ten_ten", "custom", "unknown"),
        default=None,
        help="EEG electrode layout/nomenclature system",
    )
    p.add_argument(
        "--eeg-electrode-type",
        choices=("wet", "dry", "sponge", "other", "unknown"),
        default=None,
        help="EEG electrode contact type",
    )
    p.add_argument(
        "--hrv-electrode-placement",
        choices=(
            "chest",
            "limb_leads",
            "wrist",
            "finger",
            "ear",
            "other",
            "not_applicable",
            "unknown",
        ),
        default=None,
        help="HRV sensor or electrode placement",
    )
    p.add_argument(
        "--hrv-electrode-type",
        choices=(
            "ag_agcl",
            "dry",
            "textile",
            "optical",
            "piezo",
            "other",
            "not_applicable",
            "unknown",
        ),
        default=None,
        help="HRV sensor or electrode type",
    )
    p.add_argument(
        "--eda-electrode-placement",
        choices=("palmar", "thenar", "plantar", "other"),
        default=None,
        help="EDA electrode placement site",
    )
    p.add_argument(
        "--eda-electrode-type",
        choices=("ag_agcl", "dry", "other"),
        default=None,
        help="EDA electrode material",
    )
    p.add_argument(
        "--eda-skin-prep",
        choices=("cleaned", "abraded", "cleaned_and_abraded", "none", "unknown"),
        default=None,
        help="Skin preparation before EDA electrode placement",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    log.info(
        "creating session",
        extra={
            "compound": args.compound,
            "site_id": args.site_id,
            "sponsor_id": args.sponsor_id,
            "capture_source": args.capture_source,
            "simulation_mode": args.capture_source == "simulated",
        },
    )

    session_id = create_session(
        compound=args.compound,
        site_id=args.site_id,
        sponsor_id=args.sponsor_id,
        participant_id=args.participant_id,
        capture_source=args.capture_source,
        compound_dose=args.compound_dose,
        compound_dose_unit=args.compound_dose_unit,
        protocol_arm=args.protocol_arm,
        room_id=args.room_id,
        eeg_sensor_form=args.eeg_sensor_form,
        eeg_electrode_system=args.eeg_electrode_system,
        eeg_electrode_type=args.eeg_electrode_type,
        hrv_electrode_placement=args.hrv_electrode_placement,
        hrv_electrode_type=args.hrv_electrode_type,
        eda_electrode_placement=args.eda_electrode_placement,
        eda_electrode_type=args.eda_electrode_type,
        eda_skin_prep=args.eda_skin_prep,
    )

    set_session_id(session_id)
    log.info("session created", extra={"session_id": session_id, "status": "active"})
    print(session_id)
