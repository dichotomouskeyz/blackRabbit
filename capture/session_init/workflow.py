"""Session creation workflow."""

import sys
import uuid

import psycopg2
from alembic.config import Config
from alembic.script import ScriptDirectory

from capture.session_init.metadata import _build_metadata_rows
from capture.session_init.sql import (
    _METADATA_INSERT,
    _SCHEMA_VERSION_INSERT,
    SESSION_ACTIVATE,
    SESSION_INSERT,
)
from config import settings


def _current_alembic_head() -> str:
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    return script.get_current_head()


def _postgres_version(cur) -> str:
    cur.execute("SELECT version()")
    row = cur.fetchone()
    return str(row[0]) if row else "unknown"


def _extension_version(cur, extension_name: str) -> str | None:
    cur.execute("SELECT extversion FROM pg_extension WHERE extname = %s", (extension_name,))
    row = cur.fetchone()
    return str(row[0]) if row else None


def _build_schema_version_row(cur, session_id: str, site_id: str, sponsor_id: str) -> dict:
    return {
        "session_id": session_id,
        "site_id": site_id,
        "sponsor_id": sponsor_id,
        "alembic_version": _current_alembic_head(),
        "app_version": settings.APP_VERSION,
        "python_version": sys.version,
        "postgres_version": _postgres_version(cur),
        "timescaledb_version": _extension_version(cur, "timescaledb"),
        "pgvector_version": _extension_version(cur, "vector"),
        "mne_version": None,
        "neurokit2_version": None,
        "pylsl_version": None,
    }


def create_session(
    compound: str,
    site_id: str,
    sponsor_id: str,
    participant_id: str,
    capture_source: str | None = None,
    compound_dose: float | None = None,
    compound_dose_unit: str | None = None,
    protocol_arm: str | None = None,
    room_id: str | None = None,
    eeg_sensor_form: str | None = None,
    eeg_electrode_system: str | None = None,
    eeg_electrode_type: str | None = None,
    hrv_electrode_placement: str | None = None,
    hrv_electrode_type: str | None = None,
    eda_electrode_placement: str | None = None,
    eda_electrode_type: str | None = None,
    eda_skin_prep: str | None = None,
) -> str:
    """Insert session anchor row, write 4 signal metadata rows, return session UUID."""
    settings.validate()
    capture_source = capture_source or settings.CAPTURE_SOURCE
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
                "capture_source": capture_source,
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
            capture_source=capture_source,
            eeg_sensor_form=eeg_sensor_form,
            eeg_electrode_system=eeg_electrode_system,
            eeg_electrode_type=eeg_electrode_type,
            hrv_electrode_placement=hrv_electrode_placement,
            hrv_electrode_type=hrv_electrode_type,
            eda_electrode_placement=eda_electrode_placement,
            eda_electrode_type=eda_electrode_type,
            eda_skin_prep=eda_skin_prep,
        ):
            cur.execute(_METADATA_INSERT, row)

        cur.execute(
            _SCHEMA_VERSION_INSERT,
            _build_schema_version_row(cur, session_id, site_id, sponsor_id),
        )

        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return session_id
