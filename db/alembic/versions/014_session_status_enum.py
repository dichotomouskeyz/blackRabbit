"""016 add session status enum and batch_processed_at column

Revision ID: 016_session_status_enum
Revises: 015_compression_policy
Create Date: 2026-04-27

WHY A POSTGRES ENUM INSTEAD OF A TEXT CHECK CONSTRAINT:
  Migration 006 used a TEXT column with a CHECK constraint to
  enforce valid status values. That works but has two problems:

  1. Adding a new valid status requires an ALTER TABLE with a new
     CHECK constraint — which rewrites the constraint validation
     logic for every existing row.

  2. Text with CHECK constraints don't self-document in the schema
     — you have to read the constraint to know what values are valid.

  A Postgres ENUM is a first-class type. Valid values are stored
  in the system catalog, visible in pgAdmin, and adding a new value
  is a simple ALTER TYPE ... ADD VALUE — no table rewrite required.

  The tradeoff: ENUMs are harder to remove values from (you'd need
  to recreate the type). For session status, the values are stable
  and well-understood, so ENUM is the right choice.

WHY BATCH_PROCESSED_AT:
  The watermark verification logic (Phase 4) checks that all streams
  have data up to the session close time before triggering the batch.
  When batch completes, batch_processed_at is set.

  This column is the handoff signal between Phase 3 (streaming) and
  Phase 5 (batch). A NULL batch_processed_at means "batch has not
  run yet." A non-NULL value means "batch completed at this time."

  This is also a regulatory requirement: you must be able to prove
  that post-session processing completed and when it completed.

STATUS FLOW:
  initializing → active → closing → closed (normal path)
                        → failed   (error path)
  closed → batch_processed_at set (batch complete)
"""

from typing import Sequence, Union

from alembic import op

revision: str = "014_session_status_enum"
down_revision: Union[str, None] = "013_compression_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the enum type
    op.execute("""
        CREATE TYPE session_status AS ENUM (
            'initializing',
            'active',
            'paused',
            'closing',
            'closed',
            'failed'
        );
    """)

    # Add batch_processed_at column
    op.execute("""
        ALTER TABLE sessions
        ADD COLUMN batch_processed_at TIMESTAMPTZ;
    """)

    # Migrate existing text status values to the enum
    # First add a temporary enum column
    op.execute("""
        ALTER TABLE sessions
        ADD COLUMN status_enum session_status;
    """)

    # Copy existing values across
    op.execute("""
        UPDATE sessions
        SET status_enum = status::session_status;
    """)

    # Drop the old text column and rename the enum column
    op.execute("""
        ALTER TABLE sessions DROP COLUMN status;
    """)

    op.execute("""
        ALTER TABLE sessions RENAME COLUMN status_enum TO status;
    """)

    # Add NOT NULL constraint and default
    op.execute("""
        ALTER TABLE sessions
        ALTER COLUMN status SET NOT NULL,
        ALTER COLUMN status SET DEFAULT 'initializing';
    """)


def downgrade() -> None:
    # Convert enum back to text
    op.execute("""
        ALTER TABLE sessions
        ADD COLUMN status_text TEXT;
    """)

    op.execute("""
        UPDATE sessions SET status_text = status::TEXT;
    """)

    op.execute("ALTER TABLE sessions DROP COLUMN status;")
    op.execute("ALTER TABLE sessions RENAME COLUMN status_text TO status;")
    op.execute("""
        ALTER TABLE sessions
        ALTER COLUMN status SET NOT NULL,
        ALTER COLUMN status SET DEFAULT 'initializing';
    """)

    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS batch_processed_at;")
    op.execute("DROP TYPE IF EXISTS session_status;")
