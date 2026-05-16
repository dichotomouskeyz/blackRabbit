"""029 extend echo_events zone_label to support manual_marker event labels

Revision ID: 029_echo_events_manual_marker
Revises: 028_event_composite_profiles
Create Date: 2026-05-14

WHY:
  Migration 010 created echo_events with a zone_label CHECK constraint limited
  to the four spatial proximity states used by proximity_state_change events:
    arms_reach | in_room | leaving_room | out_of_room

  The marker_simulator now publishes three event types:
    zone_enter            — actor enters a zone (same zone labels apply)
    zone_exit             — actor exits a zone  (same zone labels apply)
    manual_marker         — coordinator annotation (different labels needed)

  manual_marker events use zone_label as a structured annotation label:
    dose_administration   — dose was administered
    session_note          — general coordinator note
    participant_note      — participant-reported observation
    environmental_note    — environmental condition change

  The existing zone labels remain untouched; this migration ADDS the
  manual_marker labels to the CHECK constraint. event_type is TEXT
  with no DB-level constraint — validation is enforced by echo_handler.py.

  zone_enter and zone_exit require no schema change; they use the same
  spatial zone labels as proximity_state_change.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "029_echo_events_manual_marker"
down_revision: Union[str, None] = "028_event_composite_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE echo_events DROP CONSTRAINT IF EXISTS echo_events_zone_label_check;")
    op.execute("""
        ALTER TABLE echo_events
            ADD CONSTRAINT echo_events_zone_label_check
            CHECK (zone_label IN (
                'arms_reach',
                'in_room',
                'leaving_room',
                'out_of_room',
                'dose_administration',
                'session_note',
                'participant_note',
                'environmental_note'
            ));
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE echo_events DROP CONSTRAINT IF EXISTS echo_events_zone_label_check;")
    op.execute("""
        ALTER TABLE echo_events
            ADD CONSTRAINT echo_events_zone_label_check
            CHECK (zone_label IN (
                'arms_reach',
                'in_room',
                'leaving_room',
                'out_of_room'
            ));
    """)
