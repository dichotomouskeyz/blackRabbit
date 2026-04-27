"""002 create eeg_samples hypertable

Revision ID: 002_eeg_samples
Revises: 001_extensions
Create Date: 2026-04-26

WHY NARROW ROW FORMAT:
  Wide format = one row per timestamp, one column per channel.
  Narrow format = one row per channel per sample.

  Wide seems simpler, but it locks you into a fixed channel count.
  If you switch from an 8-channel OpenBCI to a 32-channel device,
  you'd need to ALTER TABLE to add 24 columns — and every old row
  would have NULLs in those columns. That's a schema migration on
  your highest-volume table during a trial. Bad.

  Narrow format: adding channels in 1b means more rows, not more
  columns. No schema change required. Per-channel queries (e.g.,
  "show me channel Fz for the last 5 minutes") are trivial with
  a WHERE clause.

WHY TWO TIMESTAMP COLUMNS:
  lsl_timestamp = when the sample was actually captured by the device.
  db_insert_time = when the row was written to the database.

  These are NEVER the same. Network latency, processing time, and
  buffering all create a gap. Regulatory requirement: you must be
  able to prove what was recorded vs when it was stored. If these
  were the same column, you'd lose that distinction.

WHY HYPERTABLE:
  TimescaleDB hypertables auto-partition by time. A 4-hour psilocybin
  session at 256 Hz × 8 channels = ~29 million rows. Without
  partitioning, every query scans the full table. With hypertables,
  queries only touch the relevant time chunk.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "002_eeg_samples"
down_revision: Union[str, None] = "001_extensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE eeg_samples (
            id              BIGSERIAL,
            session_id      TEXT        NOT NULL,
            participant_id  TEXT        NOT NULL,
            site_id         TEXT        NOT NULL,
            sponsor_id      TEXT        NOT NULL,
            device_id       TEXT        NOT NULL,
            channel_name    TEXT        NOT NULL,
            value           DOUBLE PRECISION NOT NULL,
            lsl_timestamp   DOUBLE PRECISION NOT NULL,
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag        SMALLINT,
            sample_index    BIGINT      NOT NULL
        );

        -- Convert to hypertable, partitioned on db_insert_time.
        -- chunk_time_interval = 1 hour. Each chunk covers 1 hour of
        -- wall-clock insertion time. For a 4-hour session, that's 4 chunks.
        SELECT create_hypertable(
            'eeg_samples',
            'db_insert_time',
            chunk_time_interval => INTERVAL '1 hour'
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eeg_samples;")
