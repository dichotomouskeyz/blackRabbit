"""009 create humen_events table

Revision ID: 009_humen_events
Revises: 008_alert_events
Create Date: 2026-04-26

WHAT HUMEN IS:
  HUMeN (Human Understanding & Mapping eNvironment) is Consensai's
  contextual layer. It captures WHERE people are relative to each
  other during a session — therapist proximity, facilitator
  presence, participant isolation vs togetherness.

  In 1a (MVP), HUMeN is manual: a coordinator taps buttons on a
  tablet to log zone transitions. These are sent as LSL Marker
  Stream events with precise timestamps, so they're time-aligned
  with all biosignal data.

  In 1b, BLE/UWB hardware replaces manual logging with continuous
  automated proximity tracking. But the table schema stays the same —
  you're just changing the source of the events.

WHY THIS MATTERS SCIENTIFICALLY:
  Most psychedelic research treats the session environment as a
  confound to control for. Consensai treats it as a measurable
  variable. "Was the therapist within arm's reach when the
  participant's EDA spiked?" is an answerable question when you
  have time-aligned HUMeN + biosignal data.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "009_humen_events"
down_revision: Union[str, None] = "008_alert_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE humen_events (
            id              BIGSERIAL   PRIMARY KEY,
            session_id      TEXT        NOT NULL,
            participant_id  TEXT        NOT NULL,
            site_id         TEXT        NOT NULL,
            sponsor_id      TEXT        NOT NULL,
            event_type      TEXT        NOT NULL
                            CHECK (event_type IN (
                                'zone_enter',
                                'zone_exit',
                                'manual_marker',
                                'proximity_change'
                            )),
            actor_id        TEXT        NOT NULL,
            actor_role      TEXT,
            zone_id         TEXT,
            zone_label      TEXT,
            metadata        JSONB       DEFAULT '{}'::jsonb,
            lsl_timestamp   DOUBLE PRECISION NOT NULL,
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS humen_events;")
