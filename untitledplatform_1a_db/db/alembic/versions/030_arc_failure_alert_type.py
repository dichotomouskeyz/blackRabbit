"""030 add arc_failure alert type

Revision ID: 030_arc_failure_alert_type
Revises: 029_echo_events_manual_marker
Create Date: 2026-05-21

WHY THIS EXISTS:
  ARC post-session failures are queryable safety/compliance events.
  They belong in alert_events so operators can filter them alongside the
  other safety/quality alerts without parsing JSONB payloads.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "030_arc_failure_alert_type"
down_revision: Union[str, None] = "029_echo_events_manual_marker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE alert_events
            DROP CONSTRAINT IF EXISTS alert_events_alert_type_check;
    """)
    op.execute("""
        ALTER TABLE alert_events
            ADD CONSTRAINT alert_events_alert_type_check
            CHECK (alert_type IN (
                'cardiac',
                'sqi',
                'respiration',
                'device_loss',
                'threshold_breach',
                'process_restart',
                'arc_failure'
            ));
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE alert_events
            DROP CONSTRAINT IF EXISTS alert_events_alert_type_check;
    """)
    op.execute("""
        ALTER TABLE alert_events
            ADD CONSTRAINT alert_events_alert_type_check
            CHECK (alert_type IN (
                'cardiac',
                'sqi',
                'respiration',
                'device_loss',
                'threshold_breach',
                'process_restart'
            ));
    """)
