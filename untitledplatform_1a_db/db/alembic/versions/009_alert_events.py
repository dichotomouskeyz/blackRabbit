"""009 create alert_events table

Revision ID: 009_alert_events
Revises: 008_audit_events
Create Date: 2026-04-26

WHY SEPARATE FROM AUDIT_EVENTS:
  audit_events is the general ledger — everything goes in there.
  alert_events is specifically for triggered safety/quality alerts
  with structured, queryable columns.

  The difference: you can query alert_events with
  "SELECT * WHERE severity = 'critical' AND compound = 'ibogaine'"
  without parsing JSONB. That query would be possible but ugly and
  slow against audit_events.

WHY ALGORITHM PROVENANCE COLUMNS:
  If software generates a context event, the row should identify what
  code path generated it, which version ran, and what parameters were
  active. In the open-source 1a MVP this is reproducibility metadata,
  not a claim of regulated clinical alert handling.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "009_alert_events"
down_revision: Union[str, None] = "008_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE alert_events (
            id                      BIGSERIAL   PRIMARY KEY,
            session_id              UUID        NOT NULL,
            participant_id          UUID        NOT NULL,
            site_id                 UUID        NOT NULL,
            sponsor_id              UUID        NOT NULL,
            alert_type              TEXT        NOT NULL
                                    CHECK (alert_type IN (
                                        'cardiac',
                                        'sqi',
                                        'respiration',
                                        'device_loss',
                                        'threshold_breach',
                                        'process_restart'
                                    )),
            compound                TEXT        NOT NULL
                                    REFERENCES compound_reference(compound_id),
            compound_dose           FLOAT,
            severity                TEXT        NOT NULL
                                    CHECK (severity IN (
                                        'info', 'warning', 'critical'
                                    )),
            stream_type             TEXT,
            channel_name            TEXT,
            trigger_value           DOUBLE PRECISION,
            threshold_value         DOUBLE PRECISION,
            algorithm_name          TEXT        NOT NULL,
            algorithm_version       TEXT        NOT NULL,
            algorithm_parameters    JSONB       NOT NULL DEFAULT '{}'::jsonb,
            message                 TEXT,
            lsl_timestamp           DOUBLE PRECISION,
            db_insert_time          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alert_events;")
