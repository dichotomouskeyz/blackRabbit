"""031 add capture mode fields for sim-to-live distinction

Revision ID: 031_capture_mode_fields
Revises: 030_arc_failure_alert_type
Create Date: 2026-05-21

WHY THIS EXISTS:
  The repository needs an explicit, persisted distinction between
  simulated and real hardware sessions. That distinction belongs on the
  session row and on the per-modality metadata rows so downstream queries
  can filter by capture provenance without relying on runtime env vars.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "031_capture_mode_fields"
down_revision: Union[str, None] = "030_arc_failure_alert_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sessions
            ADD COLUMN capture_mode TEXT NOT NULL DEFAULT 'simulated'
            CHECK (capture_mode IN ('simulated', 'hardware'));
    """)
    op.execute("""
        ALTER TABLE session_signal_metadata
            ADD COLUMN device_type TEXT NOT NULL DEFAULT 'simulated'
            CHECK (device_type IN ('simulated', 'hardware'));
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE session_signal_metadata DROP COLUMN IF EXISTS device_type;")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS capture_mode;")
