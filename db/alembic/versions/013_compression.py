"""013 enable columnar compression on all hypertables

Revision ID: 013_compression
Revises: 012_indexes
Create Date: 2026-04-27

WHY COMPRESSION:
  A real 4-hour psilocybin session produces approximately:
    - EEG:         256 Hz × 8 channels × 14400 seconds = ~29M rows
    - HRV:         ~1 Hz × 14400 seconds               = ~14K rows
    - EDA:         16 Hz × 14400 seconds               = ~230K rows
    - Respiration: 1 Hz × 14400 seconds                = ~14K rows

  Without compression, EEG alone is ~2-3 GB per session.
  With TimescaleDB columnar compression, this typically reduces
  to 10-20% of original size — so ~200-600 MB per session.

  This matters even in 1a because UCSF demos may involve real
  sessions with real participants.

HOW TIMESCALEDB COMPRESSION WORKS:
  Regular Postgres stores data row by row:
    [row1: session_id, channel, value, timestamp]
    [row2: session_id, channel, value, timestamp]
    ...

  Columnar compression stores data column by column within a chunk:
    [all session_ids in chunk] → highly compressible (same value repeated)
    [all channel_names in chunk] → highly compressible (8 repeating values)
    [all values in chunk] → compressed as a numeric array
    [all timestamps in chunk] → compressed as a delta sequence

  This works because biosignal data is highly repetitive within a chunk:
  session_id is the same for every row, channel_name cycles through 8
  values, timestamps increment by exactly 1/256th of a second.

COMPRESS_SEGMENTBY vs COMPRESS_ORDERBY:
  segmentby = session_id, channel_name
    → rows with the same session + channel are stored together.
    → Makes per-session, per-channel queries fast even on compressed data.

  orderby = lsl_timestamp DESC
    → Within each segment, rows are sorted by timestamp descending.
    → Makes "last N minutes" queries fast — they only scan the front
      of each compressed segment.

NOTE: Compression is applied by the policy in Migration 015.
This migration just enables the compression settings on each table.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "013_compression"
down_revision: Union[str, None] = "012_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # EEG: segment by session + channel so per-channel queries
    # stay fast on compressed chunks
    op.execute("""
        ALTER TABLE eeg_samples SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'session_id, channel_id',
            timescaledb.compress_orderby = 'lsl_timestamp DESC'
        );
    """)

    # HRV: segment by session + device
    op.execute("""
        ALTER TABLE hrv_samples SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'session_id, device_id',
            timescaledb.compress_orderby = 'lsl_timestamp DESC'
        );
    """)

    # EDA: segment by session + device (electrode_placement moved to
    # session_signal_metadata in migration 023)
    op.execute("""
        ALTER TABLE eda_samples SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'session_id, device_id',
            timescaledb.compress_orderby = 'lsl_timestamp DESC'
        );
    """)

    # Respiration: segment by session + device (source/is_derived moved to
    # session_signal_metadata in migration 023)
    op.execute("""
        ALTER TABLE respiration_samples SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'session_id, device_id',
            timescaledb.compress_orderby = 'lsl_timestamp DESC'
        );
    """)


def downgrade() -> None:
    # Must decompress all chunks before disabling compression settings
    op.execute("SELECT decompress_chunk(c) FROM show_chunks('eeg_samples') c;")
    op.execute("ALTER TABLE eeg_samples SET (timescaledb.compress = false);")

    op.execute("SELECT decompress_chunk(c) FROM show_chunks('hrv_samples') c;")
    op.execute("ALTER TABLE hrv_samples SET (timescaledb.compress = false);")

    op.execute("SELECT decompress_chunk(c) FROM show_chunks('eda_samples') c;")
    op.execute("ALTER TABLE eda_samples SET (timescaledb.compress = false);")

    op.execute("SELECT decompress_chunk(c) FROM show_chunks('respiration_samples') c;")
    op.execute("ALTER TABLE respiration_samples SET (timescaledb.compress = false);")
