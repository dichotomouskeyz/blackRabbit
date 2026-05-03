"""003 create eeg_samples hypertable

Revision ID: 003_eeg_samples
Revises: 002_sessions
Create Date: 2026-04-26

RECORDING-LEVEL METADATA MOVED:
  eeg_reference, sampling_frequency, power_line_frequency,
  software_filters, eeg_channel_count, cap_manufacturer, and
  cap_manufacturer_model_name are now stored in session_signal_metadata
  (migration 025). Those fields are constant across all samples from a
  given device in a given session — duplicating them on every row of a
  29-million-row hypertable wastes storage and makes the schema harder
  to reason about. session_signal_metadata holds one row per
  (session_id, modality); eeg_samples holds only what changes per sample.

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

WHY COMPOSITE PRIMARY KEY (session_id, lsl_timestamp, channel_id, db_insert_time):
  BIGSERIAL was dropped because a global sequence becomes a write
  bottleneck at 256 Hz × 8 channels. UUID provides global uniqueness
  without coordination.

  The composite PK (session_id, lsl_timestamp, channel_id) is the
  natural business key — a given electrode at a given capture time
  within a given session is exactly one sample. db_insert_time is
  appended because TimescaleDB requires the partitioning column in
  every unique constraint (including PRIMARY KEY) so it can enforce
  uniqueness within each time chunk independently.

  id UUID is retained as a surrogate reference key for foreign
  keys from other tables, but uniqueness is enforced by the PK.

WHY VOLTAGE FLOAT:
  voltage replaces the generic `value` column to make the physical
  unit explicit. EEG measures microvolt-scale electrical potential.
  FLOAT (IEEE 754 double, same storage as DOUBLE PRECISION in PG)
  is sufficient precision for biosignal data and matches the
  numpy/MNE float64 pipeline downstream.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003_eeg_samples"
down_revision: Union[str, None] = "002_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE eeg_samples (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid(),
            session_id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
            participant_id              TEXT        NOT NULL,
            site_id                     TEXT        NOT NULL,
            sponsor_id                  TEXT        NOT NULL,
            device_id                   TEXT        NOT NULL,

            -- Per-sample signal data
            channel_id                  TEXT        NOT NULL,
            voltage                     FLOAT       NOT NULL,
            lsl_timestamp               DOUBLE PRECISION NOT NULL,
            db_insert_time              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag                    SMALLINT,
            sample_index                BIGINT      NOT NULL,

            PRIMARY KEY (session_id, lsl_timestamp, channel_id, db_insert_time)
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
