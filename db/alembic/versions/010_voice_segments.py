"""010 create voice_segments table

Revision ID: 010_voice_segments
Revises: 009_humen_events
Create Date: 2026-04-26

WHY POSTGRES, NOT HYPERTABLE:
  Voice data is segment-based, not continuous. A "segment" is a
  discrete chunk of speech (e.g., 5-30 seconds) that gets processed
  post-session. This is fundamentally different from EEG/HRV/EDA
  which are continuous streams at fixed sample rates.

  The data model is: audio file reference (path to the .wav on disk)
  + extracted features per segment. The actual audio lives on local
  disk (1a) or S3 (1b) — the database stores metadata and features,
  not the audio itself.

WHY VOICE IS IN 1a AT ALL:
  NOTE: Audio capture was removed from Phase 2 scope. This table
  is planted for schema completeness — if voice analysis is added
  later, the table is already here and migrations don't need to
  be rewritten. All voice_segments rows will be NULL/empty in 1a.
  This matches the pgvector pattern: plant now, populate later.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "010_voice_segments"
down_revision: Union[str, None] = "009_humen_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE voice_segments (
            id                  BIGSERIAL   PRIMARY KEY,
            session_id          TEXT        NOT NULL,
            participant_id      TEXT        NOT NULL,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            speaker_id          TEXT,
            segment_start_sec   DOUBLE PRECISION,
            segment_end_sec     DOUBLE PRECISION,
            audio_file_ref      TEXT,
            transcription       TEXT,
            features            JSONB       DEFAULT '{}'::jsonb,
            lsl_timestamp_start DOUBLE PRECISION,
            lsl_timestamp_end   DOUBLE PRECISION,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS voice_segments;")
