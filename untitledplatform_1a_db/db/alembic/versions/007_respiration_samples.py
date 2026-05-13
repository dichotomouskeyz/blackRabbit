"""007 create respiration_samples hypertable

Revision ID: 007_respiration_samples
Revises: 006_eda_samples
Create Date: 2026-04-26

RECORDING-LEVEL METADATA MOVED:
  respiration_source (formerly 'source'), is_derived, sample_rate_hz,
  and respiration_unit (formerly 'unit') are now stored in
  session_signal_metadata (migration 022). These are properties of the
  recording setup, not of any individual sample.

WHY SOURCE COLUMN MATTERS (now in session_signal_metadata):
  Respiration data can come from two places:
    1. A chest belt (direct measurement of thoracic expansion)
    2. Derived from HRV via respiratory sinus arrhythmia (RSA)
  RSA-derived respiration is computed, not measured — it's an
  approximation extracted from the R-R interval pattern. The batch
  layer must know which source produced each session's samples because
  the error characteristics are completely different.

WHY raw_amplitude AND processed_amplitude ARE SEPARATE:
  raw_amplitude is the direct hardware output at this sample —
  never touched by any filter or transform. processed_amplitude is
  the value after whatever software_filters were applied (recorded
  in session_signal_metadata). Both are preserved because:
    1. Regulatory requirement: the original captured value must be
       recoverable if a processing bug is later discovered.
    2. The batch layer may need to re-run filtering with different
       parameters; it needs the unprocessed source.
  If no software filters were applied, both columns hold the same
  value. raw_amplitude comes directly from the device buffer.

WHY breath_phase:
  Respiration is a cyclical signal. Tagging each sample with its
  phase in the breath cycle (inhale / exhale / hold) is a
  per-sample classification that cannot be a recording-level
  constant. The capture layer optionally sets this during real-time
  peak detection; NULL means unclassified. The safety monitor can
  filter for apnea events by looking for long runs of 'hold' or
  NULL-phase samples.

WHY breaths_per_min FLOAT:
  breaths_per_min is derived from the raw respiration signal by the
  capture layer (not the batch layer) and stored alongside the raw
  value so the safety monitor has an immediately queryable rate
  without needing to run a window function at query time.

WHY COMPOSITE PRIMARY KEY (id, session_id, lsl_timestamp, db_insert_time):
  Same rationale as hrv_samples and eda_samples — UUID id for global
  uniqueness without a sequence bottleneck; db_insert_time required
  by TimescaleDB in all unique constraints on this hypertable.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "007_respiration_samples"
down_revision: Union[str, None] = "006_eda_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE respiration_samples (
            id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
            session_id          UUID        NOT NULL,
            participant_id      UUID        NOT NULL,
            site_id             UUID        NOT NULL,
            sponsor_id          UUID        NOT NULL,
            device_id           UUID        NOT NULL,

            -- Per-sample signal data
            raw_amplitude       FLOAT       NOT NULL,
            processed_amplitude FLOAT       NOT NULL,
            breath_phase        TEXT
                                CHECK (breath_phase IN ('inhale', 'exhale', 'hold')),
            breaths_per_min     FLOAT,
            lsl_timestamp       DOUBLE PRECISION NOT NULL,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag            SMALLINT,
            sample_index        BIGINT      NOT NULL,

            PRIMARY KEY (id, session_id, lsl_timestamp, db_insert_time)
        );

        SELECT create_hypertable(
            'respiration_samples',
            'db_insert_time',
            chunk_time_interval => INTERVAL '1 hour'
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS respiration_samples;")
