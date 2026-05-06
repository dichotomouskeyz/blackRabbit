"""027 create export_disclosure_log table

Revision ID: 027_export_disclosure_log
Revises: 026_data_correction_amendment_log
Create Date: 2026-05-04

WHY THIS IS DISTINCT FROM DATA_ACCESS_LOG:
  data_access_log (migration 020) records every API query — who ran
  what query and how many rows came back. It covers the routine
  read-access side of the audit trail.

  export_disclosure_log covers FORMAL DATA RELEASES — structured
  transfers of participant data outside the immediate clinical system
  to an external party. These are events with their own regulatory
  requirements:

    - Sponsor data packages require DUA (Data Use Agreement) compliance
    - FDA submissions are governed by 21 CFR 312 and require version control
    - IRB reports trigger continuing review obligations
    - DSMB packages are unblinded; their preparation requires controlled access
    - Legal requests (FOIA, litigation) require institutional review
    - Publication datasets must be de-identified per HIPAA Safe Harbor

  Each export type has different authorization requirements, recipient
  documentation requirements, and retention obligations. This table
  ensures each one is traceable from authorization through delivery.

WHY ENCRYPTION_METHOD AND TRANSFER_METHOD:
  Regulatory guidance (FDA Guidance on Electronic Records, GDPR Art. 32)
  requires that personal data transferred to third parties be protected in
  transit. Documenting the encryption method and transfer channel is the
  evidence that this obligation was met.

WHY PARTICIPANT_COUNT AND DATE_RANGE:
  For sponsor reports and regulatory submissions, the scope of the export
  must be documented: how many participants were included and what time
  window their data covers. This prevents scope disputes and ensures
  the submission can be matched to the internal dataset.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "027_export_disclosure_log"
down_revision: Union[str, None] = "026_data_correction_amendment_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE export_disclosure_log (
            id                      BIGSERIAL   PRIMARY KEY,
            site_id                 TEXT        NOT NULL,
            sponsor_id              TEXT        NOT NULL,
            session_id              TEXT,
            export_type             TEXT        NOT NULL
                                    CHECK (export_type IN (
                                        'sponsor_report',
                                        'fda_submission',
                                        'irb_report',
                                        'dsmb_package',
                                        'publication_dataset',
                                        'inter_site_transfer',
                                        'legal_request',
                                        'participant_request',
                                        'other'
                                    )),
            recipient               TEXT        NOT NULL,
            recipient_organization  TEXT,
            data_scope              TEXT        NOT NULL,
            participant_count       INTEGER,
            date_range_start        TIMESTAMPTZ,
            date_range_end          TIMESTAMPTZ,
            format                  TEXT        NOT NULL
                                    CHECK (format IN (
                                        'csv',
                                        'excel',
                                        'sas',
                                        'spss',
                                        'json',
                                        'pdf',
                                        'other'
                                    )),
            encryption_method       TEXT,
            transfer_method         TEXT        NOT NULL
                                    CHECK (transfer_method IN (
                                        'secure_portal',
                                        'encrypted_email',
                                        'physical_media',
                                        'sftp',
                                        'api',
                                        'other'
                                    )),
            authorized_by           TEXT        NOT NULL,
            exported_by             TEXT        NOT NULL,
            export_reference        TEXT,
            notes                   TEXT,
            exported_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("REVOKE UPDATE, DELETE ON export_disclosure_log FROM PUBLIC;")

    op.execute("""
        CREATE TRIGGER export_disclosure_log_audit_trigger
        AFTER INSERT ON export_disclosure_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS export_disclosure_log_audit_trigger ON export_disclosure_log;"
    )
    op.execute("DROP TABLE IF EXISTS export_disclosure_log;")
