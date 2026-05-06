"""028 create data_lock_log table

Revision ID: 028_data_lock_log
Revises: 027_export_disclosure_log
Create Date: 2026-05-04

WHAT DATA LOCK IS:
  In clinical trials, "database lock" is the formal process of freezing
  the clinical dataset before statistical analysis begins. It is a
  critical GCP milestone: once the database is locked, any further
  changes require a formal amendment process documented in
  data_correction_amendment_log (migration 026).

  Lock events and their reversals (lock-then-unlock for corrections)
  are high-visibility regulatory moments. They must be auditable with
  the exact scope of what was locked, by whom, and when.

LOCK SCOPE:
  'full_database'  — all data for a sponsor/site frozen for analysis
  'site'           — a single site's data frozen (common in multi-site trials)
  'session'        — a single session frozen post-batch processing
  'table'          — a specific table frozen (e.g., locking adverse_event_log
                     while biosignal tables remain open)
  'date_range'     — data within a specific time window frozen

LOCK TYPE:
  'soft_lock' — data is flagged as locked; application layer enforces it.
                 Amendments can be made with elevated permissions.
  'hard_lock'  — application blocks all writes to the locked scope.
                 Only a system admin can lift it.

WHY TRIGGER ON INSERT OR UPDATE:
  Data lock lifecycle involves state transitions on the same record:
    INSERT  → lock created (status = 'locked')
    UPDATE  → lock lifted (status = 'unlocked', unlocked_by set)
    UPDATE  → partial lock converted to full (status = 'locked', scope updated)

  If locks were modeled as separate INSERT rows, reconstructing the
  current lock state for a given scope would require scanning for the
  most recent row. Using a single row per lock with status transitions
  gives a clear current-state view with UPDATE history in audit_events.

  The audit trigger fires on BOTH INSERT and UPDATE so that every state
  transition — including unlocks and scope changes — is captured in
  audit_events with TG_OP = 'INSERT' or 'UPDATE' respectively.

AFFECTED_TABLES:
  A TEXT array listing the specific table names in scope when
  lock_scope = 'table'. NULL for all other scope values. Stored as
  TEXT[] rather than a JOIN table because the set is small and typically
  set once at lock time.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "028_data_lock_log"
down_revision: Union[str, None] = "027_export_disclosure_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE data_lock_log (
            id                  BIGSERIAL   PRIMARY KEY,
            site_id             TEXT        NOT NULL,
            sponsor_id          TEXT        NOT NULL,
            session_id          TEXT,
            lock_scope          TEXT        NOT NULL
                                CHECK (lock_scope IN (
                                    'full_database',
                                    'site',
                                    'session',
                                    'table',
                                    'date_range'
                                )),
            lock_type           TEXT        NOT NULL
                                CHECK (lock_type IN (
                                    'soft_lock',
                                    'hard_lock'
                                )),
            lock_status         TEXT        NOT NULL
                                CHECK (lock_status IN (
                                    'locked',
                                    'unlocked',
                                    'partial'
                                )),
            locked_at           TIMESTAMPTZ,
            locked_by           TEXT,
            lock_reference      TEXT,
            affected_tables     TEXT[],
            date_range_start    TIMESTAMPTZ,
            date_range_end      TIMESTAMPTZ,
            unlocked_at         TIMESTAMPTZ,
            unlocked_by         TEXT,
            unlock_reason       TEXT,
            notes               TEXT,
            db_insert_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TRIGGER data_lock_log_set_updated_at
        BEFORE UPDATE ON data_lock_log
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)

    # Fires on INSERT (new lock created) AND UPDATE (lock status changed).
    # See migration docstring for why both operations are audited.
    op.execute("""
        CREATE TRIGGER data_lock_log_audit_trigger
        AFTER INSERT OR UPDATE ON data_lock_log
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS data_lock_log_audit_trigger ON data_lock_log;")
    op.execute("""
        DROP TRIGGER IF EXISTS data_lock_log_set_updated_at ON data_lock_log;
        DROP TABLE IF EXISTS data_lock_log;
    """)
