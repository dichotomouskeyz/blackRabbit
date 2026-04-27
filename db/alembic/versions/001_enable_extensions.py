"""001 enable timescaledb and pgvector extensions

Revision ID: 001_extensions
Revises: None
Create Date: 2026-04-26

WHY: TimescaleDB gives us hypertables — Postgres tables optimized for
time-series data. Under the hood, it auto-partitions rows by time
into "chunks" so queries like "give me the last 5 minutes of EEG"
only scan a tiny slice of data instead of the full table.

pgvector adds a vector column type for storing embeddings. We plant
the extension now but won't populate vectors until 1b when MNE
feature extraction outputs exist.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "001_extensions"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # TimescaleDB: enables create_hypertable() for time-series tables
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

    # pgvector: enables the 'vector' column type for embeddings
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector;")
    op.execute("DROP EXTENSION IF EXISTS timescaledb CASCADE;")
