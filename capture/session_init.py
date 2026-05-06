"""Consensai 1a — Session initializer.

Creates a row in the sessions table and transitions status to 'active'.
Prints the session UUID to stdout so it can be captured and passed
directly to lsl_forwarder.py.

Usage:
    python -m capture.session_init \\
        --compound      psilocybin \\
        --site-id       <uuid> \\
        --sponsor-id    <uuid> \\
        --participant-id <uuid> \\
        [--compound-dose 25.0] \\
        [--compound-dose-unit mg] \\
        [--protocol-arm high_dose_25mg] \\
        [--room-id <uuid>]

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

VALID_COMPOUNDS = ("psilocybin", "LSD", "ibogaine", "MDMA")
VALID_DOSE_UNITS = ("mg", "ug", "µg", "mg/kg", "ug/kg", "µg/kg")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize a Consensai recording session")
    p.add_argument("--compound", required=True, choices=VALID_COMPOUNDS)
    p.add_argument("--site-id", required=True, help="Site UUID")
    p.add_argument("--sponsor-id", required=True, help="Sponsor UUID")
    p.add_argument(
        "--participant-id", required=True, help="Pseudonymous participant UUID"
    )
    p.add_argument("--compound-dose", type=float, default=None)
    p.add_argument("--compound-dose-unit", choices=VALID_DOSE_UNITS, default=None)
    p.add_argument("--protocol-arm", default=None)
    p.add_argument("--room-id", default=None)
    return p.parse_args()


def create_session(
    compound: str,
    site_id: str,
    sponsor_id: str,
    participant_id: str,
    compound_dose: float | None = None,
    compound_dose_unit: str | None = None,
    protocol_arm: str | None = None,
    room_id: str | None = None,
) -> str:
    """Insert session row, set status to active, return session UUID."""
    session_id = str(uuid.uuid4())

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()
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
        # Transition to active immediately — forwarder starts writing
        cur.execute(
            "UPDATE sessions SET status = 'active' WHERE id = %s",
            (session_id,),
        )
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
    )

    set_session_id(session_id)
    log.info("session created", extra={"session_id": session_id, "status": "active"})

    # Print UUID alone on stdout so callers can capture it with $()
    print(session_id)


if __name__ == "__main__":
    main()
