"""021 create data_correction_amendment_log table

Revision ID: 021_data_correction_amendment_log
Revises: 020_audit_triggers
Create Date: 2026-05-04

WHY THIS TABLE EXISTS:
  Data correction workflows need a structured place to preserve the
  original value, corrected value, reason, reviewer, and timestamps.

  In untitledplatform_1a, direct table UPDATEs are caught by the existing audit
  trigger infrastructure. But the audit_events payload shows only what
  the row looks like AFTER the change. This table provides the
  structured correction record — original value, corrected value, reason,
  and approval chain — in a queryable form that audit_events' JSONB
  payload does not offer.

WHY APPROVAL FIELDS EXIST:
  Some deployments want corrections reviewed before they become trusted.
  approved_by and approved_at track that optional review state. A NULL
  approved_by means the correction is pending.

CORRECTION_TYPE VOCABULARY:
  'transcription_error'   — data was entered incorrectly (typo, copy error)
  'protocol_clarification'— protocol language was ambiguous; value updated
                             per written clarification from sponsor/IRB
  'missing_data'          — field was blank; value identified and added
  'unit_error'            — value was correct but unit was wrong (mg vs µg)
  'device_calibration'    — device was out-of-calibration; value adjusted
                             per calibration correction factor
  'other'                 — requires description in correction_reason

WHY QUERY_REFERENCE:
  Many corrections originate as formal data queries (DCFs) raised by
  monitors or sponsors. query_reference links this correction back to
  the originating row in data_query_log (deferred to 1b), providing a
  complete chain from query raised → correction applied → record updated.
  In 1a the field is recorded as a free-text reference string; the
  foreign key relationship will be formalized when data_query_log is
  re-integrated.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "021_correction_amendment_log"
down_revision: Union[str, None] = "020_audit_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE data_correction_amendment_log (
            id                  BIGSERIAL   PRIMARY KEY,
            session_id          UUID        NOT NULL,
            site_id             UUID        NOT NULL,
            sponsor_id          UUID        NOT NULL,
            table_name          TEXT        NOT NULL,
            record_id           TEXT        NOT NULL,
            column_name         TEXT        NOT NULL,
            original_value      TEXT,
            corrected_value     TEXT        NOT NULL,
            correction_reason   TEXT        NOT NULL,
            correction_type     TEXT        NOT NULL
                                CHECK (correction_type IN (
                                    'transcription_error',
                                    'protocol_clarification',
                                    'missing_data',
                                    'unit_error',
                                    'device_calibration',
                                    'other'
                                )),
            requested_by        TEXT        NOT NULL,
            approved_by         TEXT,
            approved_at         TIMESTAMPTZ,
            query_reference     TEXT,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER data_correction_amendment_log_set_updated_at
        BEFORE UPDATE ON data_correction_amendment_log
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)

    # Append-only enforcement: corrections are formal records; rows must not
    # be deleted. approved_by/approved_at are set via UPDATE when the
    # correction is reviewed, which is why UPDATE is not revoked.
    op.execute("REVOKE DELETE ON data_correction_amendment_log FROM PUBLIC;")

    op.execute("""
        CREATE TRIGGER data_correction_amendment_log_audit_trigger
        AFTER INSERT ON data_correction_amendment_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS data_correction_amendment_log_audit_trigger "
        "ON data_correction_amendment_log;"
    )
    op.execute("""
        DROP TRIGGER IF EXISTS data_correction_amendment_log_set_updated_at
        ON data_correction_amendment_log;
        DROP TABLE IF EXISTS data_correction_amendment_log;
    """)
