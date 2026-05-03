"""019 create electronic_signatures table

Revision ID: 019_electronic_signatures
Revises: 018_schema_version_metadata
Create Date: 2026-04-27

WHY THIS IS NOT THE SAME AS AUDIT_EVENTS:
  audit_events records THAT something happened.
  electronic_signatures records that a HUMAN DELIBERATELY ATTESTED
  to something with legal intent — the equivalent of a handwritten
  signature on a paper form.

  21 CFR Part 11 Section 11.50 requires that electronic signatures:
    1. Are linked to the specific record they sign
    2. Include the signer's printed name
    3. Include the date and time of signing
    4. Include the MEANING of the signature
       (e.g., "session closed", "adverse event reviewed",
       "consent obtained", "dose administered")

  A coordinator ID + timestamp written to alert_events when they
  acknowledge an alert is NOT a Part 11 compliant e-signature.
  It's a logged action. This table is the legal signature record.

HOW IT WORKS:
  When a coordinator takes a signature-required action (closing a
  session, acknowledging a critical alert, confirming dose administered),
  the application writes to TWO places simultaneously:
    1. The relevant table (e.g., alert_events.acknowledged_by)
    2. This table — with the full Part 11 record

  The `record_id` and `table_name` columns link the signature back
  to the specific row it signs.

SIGNATURE_MEANING VALUES:
  These are the legally meaningful descriptions of what action
  the signature represents. They must be specific and unambiguous.

WHAT SIGNATURE_HASH IS:
  A SHA-256 hash of the signed record's content at the time of
  signing. If anyone modifies the underlying record after signing,
  the hash will no longer match. This makes tampering detectable.
  The application layer computes and stores this — the database
  stores the result.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "017_electronic_signatures"
down_revision: Union[str, None] = "016_schema_version_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE electronic_signatures (
            id                  BIGSERIAL   PRIMARY KEY,
            session_id          TEXT,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            signer_id           TEXT        NOT NULL,
            signer_printed_name TEXT        NOT NULL,
            signer_role         TEXT        NOT NULL,
            signature_meaning   TEXT        NOT NULL
                                CHECK (signature_meaning IN (
                                    'session_opened',
                                    'session_closed',
                                    'dose_administered',
                                    'adverse_event_reviewed',
                                    'adverse_event_reported',
                                    'alert_acknowledged',
                                    'consent_obtained',
                                    'protocol_deviation_logged',
                                    'data_export_authorized',
                                    'audit_review_completed'
                                )),
            table_name          TEXT        NOT NULL,
            record_id           TEXT        NOT NULL,
            signature_hash      TEXT        NOT NULL,
            signed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # Part 11 requires this table to be append-only
    op.execute("REVOKE UPDATE, DELETE ON electronic_signatures FROM PUBLIC;")

    op.execute("""
        CREATE INDEX idx_esig_session
        ON electronic_signatures (session_id);
    """)

    op.execute("""
        CREATE INDEX idx_esig_record
        ON electronic_signatures (table_name, record_id);
    """)

    op.execute("""
        CREATE INDEX idx_esig_signer
        ON electronic_signatures (signer_id, signed_at DESC);
    """)

    op.execute("""
        CREATE INDEX idx_esig_tenancy
        ON electronic_signatures (site_id, sponsor_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS electronic_signatures;")
