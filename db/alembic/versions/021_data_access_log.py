"""021 create data_access_log table

Revision ID: 021_data_access_log
Revises: 020_protocol_deviation_log
Create Date: 2026-04-27

WHY LOGGING READS, NOT JUST WRITES:
  Migration 012 added triggers that log every INSERT across all
  tables. That covers the write side of the audit trail.

  21 CFR Part 11 also requires logging READ access to regulated
  records — specifically, who accessed what data and when. The
  October 2024 FDA final guidance reinforces this: sponsors must
  maintain audit trails that capture access to records and protect
  that information from modification.

  This matters especially for participant biosignal data. If an
  unauthorized person queries a participant's EEG data, that must
  be detectable.

HOW THIS GETS POPULATED:
  Unlike write triggers (which are database-level), read logging
  must be done at the APPLICATION layer because SQL SELECT statements
  don't have native Postgres trigger support.

  The FastAPI backend (Phase 4) wraps every data query in a logging
  decorator that writes to this table before returning results.
  There is no path through the API that returns sensitive data
  without logging the access.

  Direct database connections (psql, pgAdmin) are restricted to
  admins only, and admin access itself is logged separately in
  system_user_access_log (Migration 024).

WHY QUERY_DESCRIPTION AND NOT THE FULL QUERY:
  Logging the full SQL query would expose participant data in the
  access log itself (e.g., WHERE participant_id = 'SITE01-P042').
  Instead we log a structured description of what was accessed:
  table, filters used (without values), and row count returned.
  This proves access happened without creating a second copy of
  the data.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "021_data_access_log"
down_revision: Union[str, None] = "020_protocol_deviation_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE data_access_log (
            id                  BIGSERIAL   PRIMARY KEY,
            accessor_id         TEXT        NOT NULL,
            accessor_role       TEXT        NOT NULL,
            session_id          TEXT,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            table_accessed      TEXT        NOT NULL,
            access_type         TEXT        NOT NULL
                                CHECK (access_type IN (
                                    'query',
                                    'export',
                                    'report',
                                    'audit_review'
                                )),
            query_description   TEXT        NOT NULL,
            row_count_returned  INTEGER,
            purpose             TEXT,
            accessed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("REVOKE UPDATE, DELETE ON data_access_log FROM PUBLIC;")



def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_access_log;")
