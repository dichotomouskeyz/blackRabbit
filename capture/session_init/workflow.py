"""Session creation workflow."""

import uuid

import psycopg2

from capture.session_init.metadata import _build_metadata_rows
from capture.session_init.sql import _METADATA_INSERT, SESSION_ACTIVATE, SESSION_INSERT
from config import settings

settings.validate()


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
    """Insert sessions anchor row, write 4 signal metadata rows, return session UUID."""
    session_id = str(uuid.uuid4())

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(
            SESSION_INSERT,
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
        cur.execute(SESSION_ACTIVATE, (session_id,))

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
