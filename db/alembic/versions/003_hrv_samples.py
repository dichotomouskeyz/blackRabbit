"""003 create hrv_samples hypertable

Revision ID: 003_hrv_samples
Revises: 002_eeg_samples
Create Date: 2026-04-26

WHY SEPARATE FROM EEG:
  HRV data has fundamentally different units (milliseconds between
  heartbeats), sample rate (~1 Hz vs 256 Hz for EEG), and clinical
  meaning. Cramming it into a generic "physiological_samples" table
  would mean every query needs a WHERE clause to filter by type,
  and validation rules become conditional nightmares.

  Per-modality tables = per-modality validation = per-modality
  clinical meaning. This maps cleanly to 1b where each modality
  may live in a different AWS service.

WHY R-R INTERVAL IS PRIMARY:
  Heart rate (BPM) is derived FROM R-R intervals, not the other way
  around. Storing BPM as the primary value loses precision —
  60000/72 BPM = 833.33ms, but the actual R-R might have been 834ms.
  We store the raw R-R and derive BPM when needed.

  For ibogaine sessions specifically: R-R interval monitoring is the
  most safety-critical measurement. Ibogaine can cause QT prolongation,
  and R-R variability is the early warning signal. We need the raw
  intervals, not a rounded BPM.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003_hrv_samples"
down_revision: Union[str, None] = "002_eeg_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE hrv_samples (
            id              BIGSERIAL,
            session_id      TEXT        NOT NULL,
            participant_id  TEXT        NOT NULL,
            site_id         TEXT        NOT NULL,
            sponsor_id      TEXT        NOT NULL,
            device_id       TEXT        NOT NULL,
            rr_interval_ms  DOUBLE PRECISION NOT NULL,
            heart_rate_bpm  DOUBLE PRECISION,
            beat_quality     SMALLINT,
            lsl_timestamp   DOUBLE PRECISION NOT NULL,
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag        SMALLINT,
            sample_index    BIGINT      NOT NULL
        );

        SELECT create_hypertable(
            'hrv_samples',
            'db_insert_time',
            chunk_time_interval => INTERVAL '1 hour'
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hrv_samples;")
