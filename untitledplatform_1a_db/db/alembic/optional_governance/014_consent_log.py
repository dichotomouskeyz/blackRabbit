"""014 add participant consent log

Revision ID: 014_consent_log
Revises: 013_compression_policy
Create Date: 2026-04-27

WHY THIS IS A HARD REQUIREMENT BEFORE CLINICAL USE:
  21 CFR Part 11 and FDA Good Clinical Practice (GCP) guidelines
  require that informed consent is documented BEFORE any research
  procedures begin. "Research procedures" includes biosignal capture.

  If untitledplatform_1a collects ANY biosignal data from a human participant
  at a clinical site — even in a demo context — there must be a documented
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
  IRB-approved consent forms have version numbers. If the site updates
  their consent form, all subsequent consents use the new version.
  Participants who consented under an older version may need to
  re-consent. consent_version is what lets you query:
  "which participants need to re-consent for version 2.1?"

WHY PSEUDONYMOUS_ID AND NOT REAL IDENTITY:
  Same principle as everywhere else in untitledplatform_1a. The real identity
  → pseudonymous ID mapping lives at the clinical site. We only
  ever see the pseudonymous ID. If this table were subpoenaed or
  breached, no real participant identity is exposed.

CONSENT_TYPE:
  'initial'   = first time consent for a protocol
  'updated'   = re-consent after form revision
  'reconsent' = re-consent after a protocol amendment

WHY CONSENT_METHOD:
  The method by which consent was obtained is itself a regulatory data
  point. FDA guidance distinguishes between consent obtained in person,
  via electronic signature platform, via video call, or by other means.
  Each method has different documentation requirements and audit trail
  implications. A CHECK constraint enforces a closed vocabulary so
  downstream reporting can group and filter without string normalization.

  Allowed values:
    electronic_signature — DocuSign or equivalent; has its own audit log
    in_person            — wet signature obtained at the clinical site
    video                — remote video call; typically with a recorded link
    other                — any method not covered above; requires notes field
"""

from typing import Sequence, Union

from alembic import op

revision: str = "014_consent_log"
down_revision: Union[str, None] = "013_compression_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE participant_consent_log (
            id                  BIGSERIAL   PRIMARY KEY,
            participant_id      UUID        NOT NULL,
            session_id          UUID,
            site_id             UUID        NOT NULL,
            sponsor_id          UUID        NOT NULL,
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
            consent_method      TEXT        NOT NULL
                                CHECK (consent_method IN (
                                    'electronic_signature',
                                    'in_person',
                                    'video',
                                    'other'
                                )),
            revoked_at          TIMESTAMPTZ,
            revocation_reason   TEXT,
            notes               TEXT,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS participant_consent_log;")
