"""005 create respiration_samples hypertable

Revision ID: 005_respiration_samples
Revises: 004_eda_samples
Create Date: 2026-04-26

WHY SOURCE COLUMN MATTERS:
  Respiration data can come from two places:
    1. A chest belt (direct measurement of thoracic expansion)
    2. Derived from HRV via respiratory sinus arrhythmia (RSA)

  RSA-derived respiration is computed, not measured — it's an
  approximation extracted from the R-R interval pattern. Belt
  data is ground truth. The batch layer and any downstream
  analysis MUST know which source produced each sample, because
  the error characteristics are completely different.

  This is stored as a first-class column, not metadata, because
  it determines how every downstream computation treats the data.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "005_respiration_samples"
down_revision: Union[str, None] = "004_eda_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE respiration_samples (
            id              BIGSERIAL,
            session_id      TEXT        NOT NULL,
            participant_id  TEXT        NOT NULL,
            site_id         TEXT        NOT NULL,
            sponsor_id      TEXT        NOT NULL,
            device_id       TEXT        NOT NULL,
            value           DOUBLE PRECISION NOT NULL,
            unit            TEXT        NOT NULL,
            source          TEXT        NOT NULL
                            CHECK (source IN ('belt_direct', 'rsa_derived')),
            sample_rate_hz  DOUBLE PRECISION NOT NULL,
            lsl_timestamp   DOUBLE PRECISION NOT NULL,
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag        SMALLINT,
            sample_index    BIGINT      NOT NULL
        );

        SELECT create_hypertable(
            'respiration_samples',
            'db_insert_time',
            chunk_time_interval => INTERVAL '1 hour'
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS respiration_samples;")
