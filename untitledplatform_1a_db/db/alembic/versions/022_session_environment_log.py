"""022 create session_environment_log table

Revision ID: 022_session_environment_log
Revises: 021_data_correction_amendment_log
Create Date: 2026-05-04

WHY ENVIRONMENT IS CLINICALLY RELEVANT:
  Psychedelic sessions are profoundly context-dependent. The therapeutic
  outcomes and physiological signatures observed during a psilocybin or
  MDMA session are influenced by "set and setting" — the participant's
  mindset and the physical environment. Environment is therefore not
  incidental; it is a variable.

  ICH E6(R3) requires that protocol deviations and unusual circumstances
  be documented. A room temperature spike, unexpected noise intrusion,
  or lighting change during a session could influence biosignal readings
  (EDA is particularly sensitive to temperature) or alter the participant's
  experience. Documenting these events gives the data team the context
  to flag or annotate affected data windows.

WHY APPEND-ONLY (NO UPDATE OR DELETE):
  Each row is a timestamped observation of conditions at a point in time.
  If conditions change, a new row is inserted — not the old row updated.
  This preserves the full timeline of environmental conditions throughout
  the session. Revoking UPDATE and DELETE enforces this at the database
  level; no application path can silently overwrite an earlier reading.

WHY lsl_timestamp IS NULLABLE:
  Readings logged live by the coordinator via the LSL Marker Stream carry
  an lsl_timestamp synchronized to the biosignal timeline. Readings entered
  manually after the session (e.g., reviewing a room log) do not have a
  synchronized timestamp. NULL indicates a post-hoc or approximate entry.

LIGHT_LEVEL VOCABULARY:
  'dim'      — < 10 lux (comparable to candlelight)
  'low'      — 10–100 lux (ambient evening light)
  'moderate' — 100–500 lux (standard indoor lighting)
  'bright'   — > 500 lux (clinical examination lighting)
  'other'    — requires description in the notes field

NOISE_LEVEL VOCABULARY:
  'silent'   — < 30 dB (anechoic / very quiet)
  'quiet'    — 30–50 dB (library level)
  'moderate' — 50–70 dB (conversational)
  'loud'     — > 70 dB (disruptive)
  'other'    — requires description in the notes field
"""

from typing import Sequence, Union

from alembic import op

revision: str = "022_session_environment_log"
down_revision: Union[str, None] = "021_correction_amendment_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE session_environment_log (
            id                  BIGSERIAL   PRIMARY KEY,
            session_id          UUID        NOT NULL,
            site_id             UUID        NOT NULL,
            sponsor_id          UUID        NOT NULL,
            temperature_c       FLOAT,
            humidity_percent    FLOAT
                                CHECK (humidity_percent IS NULL OR
                                       (humidity_percent >= 0 AND humidity_percent <= 100)),
            light_level         TEXT
                                CHECK (light_level IS NULL OR light_level IN (
                                    'dim', 'low', 'moderate', 'bright', 'other'
                                )),
            noise_level         TEXT
                                CHECK (noise_level IS NULL OR noise_level IN (
                                    'silent', 'quiet', 'moderate', 'loud', 'other'
                                )),
            music_playing       BOOLEAN     NOT NULL DEFAULT FALSE,
            disruptions         TEXT,
            recorded_by         TEXT        NOT NULL,
            lsl_timestamp       DOUBLE PRECISION,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("REVOKE UPDATE, DELETE ON session_environment_log FROM PUBLIC;")

    op.execute("""
        CREATE TRIGGER session_environment_log_audit_trigger
        AFTER INSERT ON session_environment_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS session_environment_log_audit_trigger "
        "ON session_environment_log;"
    )
    op.execute("DROP TABLE IF EXISTS session_environment_log;")
