"""011 add pgvector columns and session_feature_vectors table

Revision ID: 011_pgvector_columns
Revises: 010_echo_events
Create Date: 2026-04-26

WHY PLANT VECTOR COLUMNS NOW:
  Adding a column to a table that already has millions of rows is
  expensive — Postgres has to rewrite every row (or at least mark
  them for lazy update). If you wait until 1b when you have real
  session data, adding these columns means a long migration on a
  production database.

  By planting them now (nullable, defaulting to NULL), the columns
  exist from the start. When 1b populates them with actual embeddings,
  it's just an UPDATE — no schema migration needed.

WHAT GETS VECTORIZED:
  - alert_events: embed the alert context so you can do semantic
    similarity search across sessions ("find alerts similar to this one")
  - session_feature_vectors: embed MNE-computed features (band power,
    coherence, entropy) per session so you can cluster sessions by
    neurophysiological signature

  Raw EEG does NOT get vectorized. Raw EEG is millions of rows of
  voltage values — vectorizing that directly is meaningless. The
  MNE batch layer first computes features (band power, entropy,
  coherence), and THOSE features get vectorized.

NOTE ON DIMENSION SIZE:
  Using 384 dimensions as a reasonable default for sentence-transformer
  style embeddings. This will be updated when the actual embedding
  model is chosen in 1b.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "011_pgvector_columns"
down_revision: Union[str, None] = "010_echo_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add embedding column to alert_events
    op.execute("""
        ALTER TABLE alert_events
        ADD COLUMN embedding vector(384);
    """)

    # Create session_feature_vectors table for batch-computed features
    op.execute("""
        CREATE TABLE session_feature_vectors (
            id              BIGSERIAL   PRIMARY KEY,
            session_id      UUID        NOT NULL,
            site_id         UUID        NOT NULL,
            sponsor_id      UUID        NOT NULL,
            feature_type    TEXT        NOT NULL,
            feature_version TEXT        NOT NULL,
            feature_values  JSONB       NOT NULL DEFAULT '{}'::jsonb,
            embedding       vector(384),
            computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # Create session_notes table (for coordinator notes, also gets embeddings)
    op.execute("""
        CREATE TABLE session_notes (
            id              BIGSERIAL   PRIMARY KEY,
            session_id      UUID        NOT NULL,
            site_id         UUID        NOT NULL,
            sponsor_id      UUID        NOT NULL,
            author_id       TEXT        NOT NULL,
            note_type       TEXT        NOT NULL DEFAULT 'observation',
            content         TEXT        NOT NULL,
            embedding       vector(384),
            lsl_timestamp   DOUBLE PRECISION,
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS session_notes;")
    op.execute("DROP TABLE IF EXISTS session_feature_vectors;")
    op.execute("ALTER TABLE alert_events DROP COLUMN IF EXISTS embedding;")
