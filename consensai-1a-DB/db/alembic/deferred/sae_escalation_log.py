"""025 create sae_escalation_log table and expand electronic_signatures

Revision ID: 025_sae_escalation_log
Revises: 024_audit_partitioning
Create Date: 2026-05-04

WHY SAE ESCALATION IS SEPARATE FROM ADVERSE_EVENT_LOG:
  adverse_event_log (migration 018) records the clinical designation of an
  adverse event — what happened to the participant, when, how severe, and
  whether it is serious.

  sae_escalation_log records the REGULATORY REPORTING LIFECYCLE of a
  serious adverse event — who was notified, by when, via what channel,
  and what reference number was assigned. These are different clinical
  activities with different responsible parties and different timelines.

  A single SAE may generate multiple escalation rows:
    - 7-day expedited report to FDA (IND Safety Report, 21 CFR 312.32)
    - Prompt notification to IRB
    - DSMB/DSMC notification per charter
    - Sponsor medical monitor alert

  The adverse_event_log.fda_reported_at and irb_reported_at columns
  record that reporting happened. This table records HOW it happened,
  with deadline tracking and submission references for audit purposes.

FDA REPORTING TIMELINES (21 CFR 312.32):
  7-day report   — fatal or life-threatening unexpected SAE
  15-day report  — all other unexpected SAEs
  follow_up      — additional information after initial report
  annual_ims     — annual investigational medicinal product safety update

WHY TARGET_DEADLINE:
  FDA citations for late reporting are among the most common GCP findings
  at inspections. target_deadline makes the reporting obligation explicit
  and queryable. The coordinator dashboard can surface "SAE reports due
  within 48 hours" without manual tracking.

WHY SUBMISSION_REFERENCE:
  Every FDA submission receives a tracking number (e.g., MedWatch control
  number, EudraVigilance local number). Storing it here closes the loop
  from internal record to external regulatory system, enabling inspectors
  to verify that what was reported internally matches what was received
  by the agency.

ELECTRONIC SIGNATURES EXPANSION (also in this migration):
  Eight new signature_meaning values are added to support the regulatory
  workflows introduced in migrations 025-033. The existing CHECK constraint
  is dropped and recreated with the expanded vocabulary.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "025_sae_escalation_log"
down_revision: Union[str, None] = "024_audit_partitioning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Original signature_meaning values (from migration 016)
_ORIGINAL_MEANINGS = (
    "'session_opened'",
    "'session_closed'",
    "'dose_administered'",
    "'adverse_event_reviewed'",
    "'adverse_event_reported'",
    "'alert_acknowledged'",
    "'consent_obtained'",
    "'protocol_deviation_logged'",
    "'data_export_authorized'",
    "'audit_review_completed'",
)

# New values added to support migrations 025-033
_NEW_MEANINGS = (
    "'sae_escalated'",
    "'data_correction_approved'",
    "'data_locked'",
    "'data_unlocked'",
    "'randomization_assigned'",
    "'unblinding_authorized'",
    "'data_query_resolved'",
    "'rater_certified'",
)

_ALL_MEANINGS = ", ".join(_ORIGINAL_MEANINGS + _NEW_MEANINGS)
_ORIGINAL_MEANINGS_ONLY = ", ".join(_ORIGINAL_MEANINGS)


def upgrade() -> None:
    # --- Expand electronic_signatures.signature_meaning CHECK constraint ---
    op.execute("""
        ALTER TABLE electronic_signatures
        DROP CONSTRAINT electronic_signatures_signature_meaning_check;
    """)
    op.execute(f"""
        ALTER TABLE electronic_signatures
        ADD CONSTRAINT electronic_signatures_signature_meaning_check
        CHECK (signature_meaning IN ({_ALL_MEANINGS}));
    """)

    # --- Create sae_escalation_log ---
    op.execute("""
        CREATE TABLE sae_escalation_log (
            id                      BIGSERIAL   PRIMARY KEY,
            adverse_event_id        BIGINT      NOT NULL,
            session_id              TEXT        NOT NULL,
            participant_id          TEXT        NOT NULL,
            site_id                 TEXT        NOT NULL,
            sponsor_id              TEXT        NOT NULL,
            escalation_type         TEXT        NOT NULL
                                    CHECK (escalation_type IN (
                                        'fda_ind_safety_report',
                                        'irb_expedited_report',
                                        'dsmb_notification',
                                        'sponsor_medical_monitor',
                                        'data_safety_monitor',
                                        'regulatory_authority',
                                        'susar'
                                    )),
            report_type             TEXT        NOT NULL
                                    CHECK (report_type IN (
                                        '7_day',
                                        '15_day',
                                        'follow_up',
                                        'annual_ims',
                                        'initial_susar',
                                        'follow_up_susar',
                                        'other'
                                    )),
            target_deadline         TIMESTAMPTZ NOT NULL,
            submitted_at            TIMESTAMPTZ,
            submitted_by            TEXT,
            submission_reference    TEXT,
            submission_method       TEXT
                                    CHECK (submission_method IS NULL OR
                                           submission_method IN (
                                               'fdaerr',
                                               'eudravigilance',
                                               'secure_portal',
                                               'email',
                                               'fax',
                                               'mail',
                                               'other'
                                           )),
            narrative               TEXT        NOT NULL,
            follow_up_required      BOOLEAN     NOT NULL DEFAULT FALSE,
            follow_up_due_at        TIMESTAMPTZ,
            notes                   TEXT,
            db_insert_time          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER sae_escalation_log_set_updated_at
        BEFORE UPDATE ON sae_escalation_log
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)

    op.execute("""
        CREATE TRIGGER sae_escalation_log_audit_trigger
        AFTER INSERT ON sae_escalation_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS sae_escalation_log_audit_trigger ON sae_escalation_log;"
    )
    op.execute("""
        DROP TRIGGER IF EXISTS sae_escalation_log_set_updated_at ON sae_escalation_log;
        DROP TABLE IF EXISTS sae_escalation_log;
    """)

    op.execute("""
        ALTER TABLE electronic_signatures
        DROP CONSTRAINT electronic_signatures_signature_meaning_check;
    """)
    op.execute(f"""
        ALTER TABLE electronic_signatures
        ADD CONSTRAINT electronic_signatures_signature_meaning_check
        CHECK (signature_meaning IN ({_ORIGINAL_MEANINGS_ONLY}));
    """)
