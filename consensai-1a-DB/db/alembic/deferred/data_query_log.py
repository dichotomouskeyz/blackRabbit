"""031 create data_query_log table

Revision ID: 031_data_query_log
Revises: 030_randomization_unblinding_log
Create Date: 2026-05-04

WHAT A DATA QUERY IS:
  In clinical trials, a "data query" (also called a Data Clarification Form,
  or DCF) is a formal question raised against a specific data point in the
  CRF when a value appears missing, inconsistent, or implausible. Queries
  are a core mechanism of clinical data management:

    - A monitor reviewing session notes may query: "Subject reported
      mild nausea at T+2h but adverse_event_log has no corresponding entry."
    - A sponsor may query: "Dosing weight recorded as 180 — confirm units
      are lbs, not kg."
    - The system may auto-raise a query when a biosignal value exceeds a
      plausibility threshold.

  ICH E6(R3) Section 5.18.4 requires that all data changes in a trial's
  electronic data capture system be traceable to the query that prompted
  them. This table is that trace.

QUERY LIFECYCLE:
  open        → query raised; no response yet
  answered    → site has responded; pending sponsor/monitor review
  closed      → response accepted; query resolved (no data change required)
  cancelled   → query raised in error or made moot by a protocol clarification

  When a query results in a data correction, the corresponding row in
  data_correction_amendment_log (migration 026) references this query's
  id via query_reference. That forms the complete chain:
    query raised → data correction applied → query closed.

QUERY_TYPE VOCABULARY:
  'data_clarification'   — value is ambiguous or requires explanation
  'missing_data'         — required field is blank or NULL
  'inconsistency'        — two data points contradict each other
  'plausibility_check'   — value falls outside expected physiological range
  'protocol_deviation'   — data suggests a protocol deviation occurred
  'other'                — requires explanation in query_text

WHY lsl_timestamp IS NULLABLE:
  Queries raised by the system during live monitoring can carry an
  lsl_timestamp tied to the specific biosignal sample that triggered
  the query. Queries raised by a human reviewer post-session have no
  associated biosignal timestamp — the field is NULL in those cases.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "031_data_query_log"
down_revision: Union[str, None] = "030_randomization_unblinding_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE data_query_log (
            id                  BIGSERIAL   PRIMARY KEY,
            session_id          TEXT        NOT NULL,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            table_name          TEXT        NOT NULL,
            record_id           TEXT        NOT NULL,
            field_name          TEXT        NOT NULL,
            query_type          TEXT        NOT NULL
                                CHECK (query_type IN (
                                    'data_clarification',
                                    'missing_data',
                                    'inconsistency',
                                    'plausibility_check',
                                    'protocol_deviation',
                                    'other'
                                )),
            query_status        TEXT        NOT NULL DEFAULT 'open'
                                CHECK (query_status IN (
                                    'open',
                                    'answered',
                                    'closed',
                                    'cancelled'
                                )),
            query_text          TEXT        NOT NULL,
            response_text       TEXT,
            raised_by           TEXT        NOT NULL,
            responded_by        TEXT,
            resolved_by         TEXT,
            lsl_timestamp       DOUBLE PRECISION,
            raised_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            responded_at        TIMESTAMPTZ,
            resolved_at         TIMESTAMPTZ,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER data_query_log_set_updated_at
        BEFORE UPDATE ON data_query_log
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)

    op.execute("""
        CREATE TRIGGER data_query_log_audit_trigger
        AFTER INSERT ON data_query_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS data_query_log_audit_trigger " "ON data_query_log;"
    )
    op.execute("""
        DROP TRIGGER IF EXISTS data_query_log_set_updated_at
        ON data_query_log;
        DROP TABLE IF EXISTS data_query_log;
    """)
