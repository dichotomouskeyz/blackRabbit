"""010 create echo_events table

Revision ID: 010_echo_events
Revises: 009_alert_events
Create Date: 2026-04-26

WHAT ECHO IS:
  ECHO (Human Understanding & Mapping eNvironment) is untitledplatform_1a's
  contextual layer. It captures WHERE people are relative to each
  other during a session — therapist proximity, facilitator
  presence, participant isolation vs togetherness.

  In 1a (MVP), ECHO is manual: a coordinator taps buttons on a
  tablet to log proximity state transitions. These are sent as LSL
  Marker Stream events with precise timestamps, so they're
  time-aligned with all biosignal data. The `source` column is
  always 'manual_logging' in 1a.

  In 1b, IMU inference in hardware will derive proximity events automatically.
  Those rows will carry source='imu_derived'. The schema is forward-
  compatible — only the source changes, not the table structure.

  IMU hardware is OUT OF SCOPE for 1a. Do not populate imu_derived
  rows or build inference logic until 1b is explicitly scoped.

PROXIMITY STATES (zone_label):
  arms_reach    — actor is within arm's reach of the participant;
                  coordinator presses button when this is true
  in_room       — actor is in the room but beyond arm's reach;
                  the default state when no closer contact is logged
  leaving_room  — actor is actively in the process of leaving;
                  pressed as the actor moves toward the exit so the
                  transition is time-stamped precisely
  out_of_room   — actor has left the room entirely

WHY THIS MATTERS SCIENTIFICALLY:
  Most psychedelic research treats the session environment as a
  confound to control for. untitledplatform_1a treats it as a measurable
  variable. "Was the therapist within arm's reach when the
  participant's EDA spiked?" is an answerable question when you
  have time-aligned ECHO + biosignal data.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "010_echo_events"
down_revision: Union[str, None] = "009_alert_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE echo_events (
            id               BIGSERIAL        PRIMARY KEY,
            session_id       UUID             NOT NULL,
            participant_id   UUID             NOT NULL,
            site_id          UUID             NOT NULL,
            sponsor_id       UUID             NOT NULL,
            event_type       TEXT             NOT NULL
                             CHECK (event_type IN (
                                 'proximity_reach',
                                 'proximity_in_room',
                                 'proximity_leaving_room',
                                 'proximity_out_of_room'
                             )),
            source           TEXT             NOT NULL
                             CHECK (source IN (
                                 'manual_logging',
                                 'imu_derived'
                             )),
            actor_id         TEXT             NOT NULL,
            actor_role       TEXT,
            zone_id          TEXT,
            zone_label       TEXT             NOT NULL
                             CHECK (zone_label IN (
                                 'arms_reach',
                                 'in_room',
                                 'leaving_room',
                                 'out_of_room'
                             )),
            sample_index     BIGINT,
            confidence_score FLOAT,
                             CHECK (confidence_score IS NULL OR
                                    (confidence_score >= 0.0 AND confidence_score <= 1.0)),
            metadata         JSONB            DEFAULT '{}'::jsonb,
            lsl_timestamp    DOUBLE PRECISION NOT NULL,
            db_insert_time   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS echo_events;")
