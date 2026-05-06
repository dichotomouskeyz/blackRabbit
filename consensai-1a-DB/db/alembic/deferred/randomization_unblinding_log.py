"""030 create randomization_unblinding_log table

Revision ID: 030_randomization_unblinding_log
Revises: 029_user_role_permission_log
Create Date: 2026-05-04

WHY RANDOMIZATION TRACKING MATTERS HERE:
  Psychedelic trials frequently use blinded or double-blinded designs —
  particularly for MDMA and psilocybin where active-dose vs placebo
  discrimination by participants is a known confound. The randomization
  record must be:
    1. Generated independently of the site (central randomization)
    2. Sealed until the point of administration
    3. Traceable to a specific participant and session
    4. Formally documented when any unblinding occurs

  This table captures the full lifecycle: randomization assignment at
  enrollment, through any emergency or scheduled unblinding events.

TREATMENT_ARM BLINDING:
  treatment_arm is intentionally nullable and stored even after
  unblinding. Prior to unblinding, the column is NULL at the site level
  (even if the central randomization database holds the assignment).
  After unblinding, it is populated. The transition from NULL → value
  is captured in audit_events via the audit trigger.

EMERGENCY UNBLINDING:
  Protocol requires that emergency unblinding (e.g., a serious adverse
  event where treatment assignment is clinically necessary) be documented
  separately from scheduled or end-of-trial unblinding. The
  emergency_unblinding flag enables instant identification of unplanned
  unblinding events in audits. Emergency unblinding without a documented
  clinical justification (unblinding_reason) is a major protocol deviation.

WHY DSMB_NOTIFIED:
  Many trial protocols require the Data Safety Monitoring Board to be
  notified whenever emergency unblinding occurs, regardless of whether
  the event is reported as a SAE. The dsmb_notified and dsmb_notified_at
  columns track this obligation independently of the sae_escalation_log.

RANDOMIZATION_SEQUENCE_NUMBER:
  The sequential position in the randomization list. Required for ICH E9
  compliance — the sequence number lets the statistician verify that
  randomization was performed according to the pre-specified scheme.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "030_randomization_unblinding_log"
down_revision: Union[str, None] = "029_user_role_permission_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE randomization_unblinding_log (
            id                          BIGSERIAL   PRIMARY KEY,
            session_id                  TEXT        NOT NULL,
            participant_id              TEXT        NOT NULL,
            site_id                     TEXT        NOT NULL,
            sponsor_id                  TEXT        NOT NULL,
            event_type                  TEXT        NOT NULL
                                        CHECK (event_type IN (
                                            'randomization',
                                            'unblinding_request',
                                            'emergency_unblinding',
                                            'scheduled_unblinding',
                                            'end_of_trial_unblinding',
                                            'unblinding_reverted'
                                        )),
            treatment_arm               TEXT,
            randomization_code          TEXT,
            randomization_sequence_number INTEGER,
            randomized_at               TIMESTAMPTZ,
            randomized_by               TEXT,
            unblinding_reason           TEXT,
            unblinding_authorized_by    TEXT,
            unblinded_at                TIMESTAMPTZ,
            emergency_unblinding        BOOLEAN     NOT NULL DEFAULT FALSE,
            dsmb_notified               BOOLEAN     NOT NULL DEFAULT FALSE,
            dsmb_notified_at            TIMESTAMPTZ,
            notes                       TEXT,
            db_insert_time              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER randomization_unblinding_log_set_updated_at
        BEFORE UPDATE ON randomization_unblinding_log
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)

    op.execute("""
        CREATE TRIGGER randomization_unblinding_log_audit_trigger
        AFTER INSERT ON randomization_unblinding_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS randomization_unblinding_log_audit_trigger "
        "ON randomization_unblinding_log;"
    )
    op.execute("""
        DROP TRIGGER IF EXISTS randomization_unblinding_log_set_updated_at
        ON randomization_unblinding_log;
        DROP TABLE IF EXISTS randomization_unblinding_log;
    """)
