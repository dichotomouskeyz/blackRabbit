"""005 create hrv_samples hypertable

Revision ID: 005_hrv_samples
Revises: 004_eeg_samples
Create Date: 2026-04-26

RECORDING-LEVEL METADATA MOVED:
  signal_source, beat_detection_algorithm, beat_detection_version,
  software_filters, and power_line_frequency are now stored in
  session_signal_metadata (migration 022). These fields describe the
  recording setup, not individual R-R intervals. Storing them once per
  (session_id, 'hrv') row is correct; duplicating them across every
  beat sample is not.

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

WHY COMPOSITE PRIMARY KEY (id, session_id, lsl_timestamp, db_insert_time):
  HRV has no channel dimension, so (session_id, lsl_timestamp) alone
  is not guaranteed unique under concurrent inserts or device restarts.
  UUID id provides global uniqueness without a sequence bottleneck.
  session_id and lsl_timestamp are included in the PK for query
  locality — TimescaleDB can use the PK to skip chunks on time-range
  queries. db_insert_time is required by TimescaleDB in all unique
  constraints on a hypertable partitioned by that column.

WHY FLOAT FOR rr_interval_ms AND heart_rate_bpm:
  FLOAT (IEEE 754 double) matches the native precision of biosignal
  hardware and the numpy/Neurokit2 pipeline. DOUBLE PRECISION is an
  alias for the same type in PostgreSQL — FLOAT is used here for
  explicit clarity in the schema.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "005_hrv_samples"
down_revision: Union[str, None] = "004_eeg_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE hrv_samples (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid(),
            session_id                  UUID        NOT NULL,
            participant_id              UUID        NOT NULL,
            site_id                     UUID        NOT NULL,
            sponsor_id                  UUID        NOT NULL,
            device_id                   UUID        NOT NULL,

            -- Per-sample signal data
            rr_interval_ms              FLOAT       NOT NULL,
            heart_rate_bpm              FLOAT,
            beat_quality                SMALLINT,
            lsl_timestamp               DOUBLE PRECISION NOT NULL,
            db_insert_time              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag                    SMALLINT,
            sample_index                BIGINT      NOT NULL,

            PRIMARY KEY (id, session_id, lsl_timestamp, db_insert_time)
        );

        SELECT create_hypertable(
            'hrv_samples',
            'db_insert_time',
            chunk_time_interval => INTERVAL '1 hour'
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hrv_samples;")
