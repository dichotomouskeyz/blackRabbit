"""Pre-flight checks for capture sessions.

`run_preflight` is the entry point: it opens one DB connection, verifies the
session is ready, loads per-session config, and closes the connection. The
check functions accept the connection so callers (and future supervisors) can
reuse their own.

Failures raise typed exceptions (all RuntimeError subclasses, so existing
fatal-error handling keeps working) instead of bare RuntimeError.
"""

import json

import psycopg2

from capture.forwarder.models import SessionConfig
from config import settings


class PreflightError(RuntimeError):
    """Base class for preflight failures."""


class SessionNotFoundError(PreflightError):
    """No sessions row for this session_id/sponsor_id."""


class SessionNotActiveError(PreflightError):
    """Session exists but is not in 'active' status."""


class MissingModalityError(PreflightError):
    """session_signal_metadata rows are missing for required modalities."""


def run_preflight(cfg: SessionConfig) -> SessionConfig:
    """Verify session readiness and load session config over one connection."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    try:
        verify_session_ready(cfg, conn)
        return load_session_config(cfg, conn)
    finally:
        conn.close()


def verify_session_ready(cfg: SessionConfig, conn) -> None:
    """Confirm the session can receive biosignal samples before capture starts."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM sessions WHERE id = %s AND sponsor_id = %s",
            (cfg.session_id, cfg.sponsor_id),
        )
        row = cur.fetchone()

    if row is None:
        raise SessionNotFoundError(
            f"Session {cfg.session_id!r} not found - run session_init before starting the forwarder"
        )

    status = str(row[0])
    if status != "active":
        raise SessionNotActiveError(
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

    missing = settings.REQUIRED_MODALITIES - present
    if missing:
        raise MissingModalityError(
            f"Session {cfg.session_id!r} is missing signal metadata for: "
            f"{sorted(missing)} - re-run session_init to rebuild metadata rows"
        )


def load_session_config(cfg: SessionConfig, conn) -> SessionConfig:
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
        raise PreflightError(
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
