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
    p.add_argument("--protocol-arm", default=None)
    p.add_argument("--room-id", type=_parse_uuid, default=None, help="Room UUID")
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
    print(session_id)
