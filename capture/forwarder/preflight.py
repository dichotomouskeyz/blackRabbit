"""Pre-flight checks for capture sessions."""

import json

import psycopg2

from capture.forwarder.models import SessionConfig
from config import settings

_REQUIRED_MODALITIES = frozenset({"eeg", "hrv", "eda", "respiration"})


def _verify_session_ready(cfg: SessionConfig) -> None:
    """Confirm the session can receive biosignal samples before capture starts."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM sessions WHERE id = %s AND sponsor_id = %s",
                (cfg.session_id, cfg.sponsor_id),
            )
            row = cur.fetchone()

        if row is None:
            raise RuntimeError(
                f"Session {cfg.session_id!r} not found - "
                "run session_init before starting the forwarder"
            )

        status = str(row[0])
        if status != "active":
            raise RuntimeError(
                f"Session {cfg.session_id!r} has status {status!r}, expected 'active' - "
                "session is not ready to receive samples"
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT modality
                FROM session_signal_metadata
                WHERE session_id = %s
                  AND sponsor_id = %s
                """,
                (cfg.session_id, cfg.sponsor_id),
            )
            present = {r[0] for r in cur.fetchall()}

        missing = _REQUIRED_MODALITIES - present
        if missing:
            raise RuntimeError(
                f"Session {cfg.session_id!r} is missing signal metadata for: "
                f"{sorted(missing)} - re-run session_init to rebuild metadata rows"
            )
    finally:
        conn.close()


def _load_session_config(cfg: SessionConfig) -> SessionConfig:
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT eeg_channel_names
                FROM session_signal_metadata
                WHERE session_id = %s
                  AND sponsor_id = %s
                  AND modality = 'eeg'
                """,
                (cfg.session_id, cfg.sponsor_id),
            )
            row = cur.fetchone()

        if row is None or row[0] is None:
            return cfg

        raw_names = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        channel_names = tuple(str(name) for name in raw_names)
        if len(channel_names) != settings.EEG_CHANNEL_COUNT:
            raise RuntimeError(
                f"Session {cfg.session_id!r} has {len(channel_names)} EEG channel names "
                f"but EEG_CHANNEL_COUNT is {settings.EEG_CHANNEL_COUNT}"
            )
        return SessionConfig(
            session_id=cfg.session_id,
            participant_id=cfg.participant_id,
            site_id=cfg.site_id,
            sponsor_id=cfg.sponsor_id,
            eeg_channel_names=channel_names,
        )
    finally:
        conn.close()


verify_session_ready = _verify_session_ready
load_session_config = _load_session_config
