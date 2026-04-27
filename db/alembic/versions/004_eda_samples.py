"""004 create eda_samples hypertable

Revision ID: 004_eda_samples
Revises: 003_hrv_samples
Create Date: 2026-04-26

WHY EDA GETS ITS OWN TABLE:
  EDA (electrodermal activity / galvanic skin response) measures
  sweat gland activity via skin conductance. It's the primary
  autonomic arousal signal — when someone has an emotionally
  significant experience, EDA spikes within 1-4 seconds.

  For psychedelic sessions, EDA is the fastest autonomic indicator
  of subjective intensity. Combined with HRV and EEG, it forms
  the triangulation that makes Consensai's signal useful.

  Raw unit is microsiemens (µS). The batch layer (Neurokit2)
  decomposes this into tonic (baseline) and phasic (event-related)
  components post-session using cvxEDA.

WHY ELECTRODE_PLACEMENT AND SAMPLE_RATE_HZ:
  Different devices place EDA electrodes differently (palmar,
  thenar, plantar) and sample at different rates (4-32 Hz).
  Both affect signal interpretation. These are first-class columns,
  not buried in a JSONB blob, because the batch layer needs them
  for correct processing.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "004_eda_samples"
down_revision: Union[str, None] = "003_hrv_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE eda_samples (
            id                  BIGSERIAL,
            session_id          TEXT        NOT NULL,
            participant_id      TEXT        NOT NULL,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            device_id           TEXT        NOT NULL,
            conductance_us      DOUBLE PRECISION NOT NULL,
            electrode_placement TEXT        NOT NULL,
            sample_rate_hz      DOUBLE PRECISION NOT NULL,
            signal_quality      SMALLINT,
            lsl_timestamp       DOUBLE PRECISION NOT NULL,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag            SMALLINT,
            sample_index        BIGINT      NOT NULL
        );

        SELECT create_hypertable(
            'eda_samples',
            'db_insert_time',
            chunk_time_interval => INTERVAL '1 hour'
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eda_samples;")
