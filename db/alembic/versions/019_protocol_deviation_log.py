"""019 create protocol_deviation_log table

Revision ID: 019_protocol_deviation_log
Revises: 018_adverse_event_log
Create Date: 2026-04-27

WHAT A PROTOCOL DEVIATION IS:
  A protocol deviation is any departure from the IRB-approved
  study protocol. Examples in a psychedelic session context:
    - Session ran 30 minutes longer than the approved window
    - Dose administered was outside the approved range
    - Session monitor left the room (protocol requires presence)
    - Prohibited concomitant medication taken before session
    - Participant did not complete the required prep session
    - Data collection equipment failed mid-session

  Deviations are not necessarily bad — equipment fails, emergencies
  happen. But they MUST be documented, classified, and reported
  to the IRB. Undocumented deviations are protocol violations that
  can invalidate trial data and result in FDA findings.

MAJOR VS MINOR DEVIATION:
  Minor — deviation unlikely to affect participant safety or data
          integrity. Reported to IRB in aggregate at continuing
          review (annually). Example: session ran 5 minutes over.

  Major — deviation that may affect participant safety, data
          integrity, or the rights of the participant. Requires
          prompt IRB reporting (within days). Example: wrong dose
          administered, participant left unsupervised during peak.

CORRECTIVE AND PREVENTIVE ACTION (CAPA):
  For major deviations, the IRB and FDA expect documentation of
  what was done to prevent recurrence. This is called a CAPA.
  The capa_description column records that plan.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "019_protocol_deviation_log"
down_revision: Union[str, None] = "018_adverse_event_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE protocol_deviation_log (
            id                  BIGSERIAL   PRIMARY KEY,
            session_id          TEXT        NOT NULL,
            participant_id      TEXT        NOT NULL,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            deviation_type      TEXT        NOT NULL,
            classification      TEXT        NOT NULL
                                CHECK (classification IN (
                                    'minor',
                                    'major'
                                )),
            description         TEXT        NOT NULL,
            deviation_timestamp TIMESTAMPTZ NOT NULL,
            discovered_by       TEXT        NOT NULL,
            discovered_at       TIMESTAMPTZ NOT NULL,
            impact_on_safety    TEXT,
            impact_on_data      TEXT,
            immediate_action    TEXT,
            capa_description    TEXT,
            irb_reported_at     TIMESTAMPTZ,
            sponsor_reported_at TIMESTAMPTZ,
            notes               TEXT,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)



def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS protocol_deviation_log;")
