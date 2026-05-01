"""017 add participant consent log

Revision ID: 017_consent_log
Revises: 016_session_status_enum
Create Date: 2026-04-27

WHY THIS IS A HARD REQUIREMENT BEFORE UCSF:
  21 CFR Part 11 and FDA Good Clinical Practice (GCP) guidelines
  require that informed consent is documented BEFORE any research
  procedures begin. "Research procedures" includes biosignal capture.

  If Consensai collects ANY biosignal data from a human participant
  at UCSF — even in a demo context — there must be a documented
  consent record tied to that participant's pseudonymous ID.

  Without this table, the system is non-compliant for any human
  data collection regardless of how the session is framed.

WHY STANDALONE TABLE (NOT PART OF SESSIONS):
  Consent has its own lifecycle that is independent of sessions:
    - A participant can consent once and participate in multiple sessions
    - Consent can be revoked between sessions
    - Consent version may change if the consent form is updated
    - A participant may consent but never actually have a session

  If consent lived in the sessions table:
    - You'd duplicate consent data across every session
    - Revocation would require updating multiple rows
    - Consent version history would be lost

  Standalone table = one consent record per consent event,
  independent of how many sessions that participant has.

WHY CONSENT_VERSION:
  IRB-approved consent forms have version numbers. If UCSF updates
  their consent form, all subsequent consents use the new version.
  Participants who consented under an older version may need to
  re-consent. consent_version is what lets you query:
  "which participants need to re-consent for version 2.1?"

WHY PSEUDONYMOUS_ID AND NOT REAL IDENTITY:
  Same principle as everywhere else in Consensai. The real identity
  → pseudonymous ID mapping lives at the clinical site. We only
  ever see the pseudonymous ID. If this table were subpoenaed or
  breached, no real participant identity is exposed.

CONSENT_TYPE:
  'initial'  = first time consent for a protocol
  'updated'  = re-consent after form revision
  'reconsent'= re-consent after a protocol amendment
"""

from typing import Sequence, Union

from alembic import op

revision: str = "017_consent_log"
down_revision: Union[str, None] = "016_session_status_enum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE participant_consent_log (
            id                  BIGSERIAL   PRIMARY KEY,
            participant_id      TEXT        NOT NULL,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            protocol_id         TEXT        NOT NULL,
            consent_version     TEXT        NOT NULL,
            consent_type        TEXT        NOT NULL
                                CHECK (consent_type IN (
                                    'initial',
                                    'updated',
                                    'reconsent'
                                )),
            consented_at        TIMESTAMPTZ NOT NULL,
            consent_obtained_by TEXT        NOT NULL,
            revoked_at          TIMESTAMPTZ,
            revocation_reason   TEXT,
            notes               TEXT,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # Indexes for the most common queries:
    # "Does this participant have valid consent for this protocol?"
    # "Show me all consents for this site"
    op.execute("""
        CREATE INDEX idx_consent_participant_protocol
        ON participant_consent_log (participant_id, protocol_id);
    """)

    op.execute("""
        CREATE INDEX idx_consent_tenancy
        ON participant_consent_log (site_id, sponsor_id);
    """)

    # Index for finding active (non-revoked) consents
    op.execute("""
        CREATE INDEX idx_consent_active
        ON participant_consent_log (participant_id, protocol_id)
        WHERE revoked_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS participant_consent_log;")
