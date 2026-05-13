"""Pre-flight checks for capture sessions."""

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
                "SELECT status FROM sessions WHERE id = %s",
                (cfg.session_id,),
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
                "SELECT modality FROM session_signal_metadata WHERE session_id = %s",
                (cfg.session_id,),
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
