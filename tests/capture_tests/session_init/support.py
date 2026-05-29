"""Shared constants and DB helpers for session_init test modules."""

from unittest.mock import patch

import psycopg2

from capture.session_init.workflow import create_session
from config import settings

_SITE = "f1d00007-0000-4444-cccc-000000000001"
_SPONSOR = "f1d00007-0000-4444-dddd-000000000001"
_PART = "f1d00007-0000-4444-bbbb-000000000001"
_COMPOUND = "psilocybin"


def _conn(db_url: str) -> psycopg2.extensions.connection:
    c = psycopg2.connect(db_url)
    c.autocommit = True
    return c


def _query_session(db_url: str, session_id: str) -> tuple | None:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT site_id, sponsor_id, participant_id, capture_mode, compound,
               compound_dose, compound_dose_unit, protocol_arm, room_id,
               status, started_at
        FROM sessions WHERE id = %s
        """,
        (session_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def _query_audit(db_url: str, session_id: str) -> list[tuple]:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        "SELECT event_type, table_name FROM audit_events WHERE session_id = %s ORDER BY id",
        (session_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def _query_metadata(db_url: str, session_id: str) -> list[dict]:
    conn = _conn(db_url)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT modality,
               device_type,
               power_line_frequency, sample_rate_hz,
               eeg_reference, sampling_frequency, eeg_channel_count, eeg_channel_names,
               cap_manufacturer, cap_manufacturer_model_name,
               hrv_signal_source, beat_detection_algorithm, beat_detection_version,
               electrode_placement, electrode_type, skin_prep,
               eda_signal_source, eda_range_min_us, eda_range_max_us,
               respiration_source, is_derived, respiration_unit,
               site_id, sponsor_id, participant_id, device_id
        FROM session_signal_metadata
        WHERE session_id = %s
        ORDER BY CASE modality
            WHEN 'eeg' THEN 0 WHEN 'hrv' THEN 1
            WHEN 'eda' THEN 2 WHEN 'respiration' THEN 3
        END
        """,
        (session_id,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def _cleanup(db_url: str, *session_ids: str) -> None:
    conn = _conn(db_url)
    cur = conn.cursor()
    for sid in session_ids:
        cur.execute("DELETE FROM session_signal_metadata WHERE session_id = %s", (sid,))
        cur.execute("DELETE FROM audit_events WHERE session_id = %s", (sid,))
        cur.execute("DELETE FROM sessions WHERE id = %s", (sid,))
    cur.close()
    conn.close()


def _call(db_url: str, **kwargs) -> str:
    defaults = dict(
        compound=_COMPOUND,
        site_id=_SITE,
        sponsor_id=_SPONSOR,
        participant_id=_PART,
    )
    defaults.update(kwargs)
    with patch.object(settings, "DATABASE_URL", db_url):
        return create_session(**defaults)
