"""020 create audit triggers on low-volume tables

Revision ID: 020_audit_triggers
Revises: 019_session_signal_metadata
Create Date: 2026-05-02

WHY THIS RUNS LAST (among table-creation migrations):
  Audit triggers must be attached AFTER the tables they watch exist.
  This migration runs after every table in the 1a schema has been
  created, so a single migration can cover the full table set without
  spreading trigger attachments across individual table migrations.

  Tables deferred to 1b (protocol_deviation_log, data_access_log,
  system_users, system_user_access_log, and the compliance log tables)
  will have their triggers attached in the migration that creates them
  when they are re-integrated.

HOW TRIGGERS WORK:
  A database trigger is a function that Postgres runs automatically
  when a specific event happens on a table. Here we attach triggers to
  low-volume governance and metadata tables so that every INSERT also
  writes a row to audit_events.

  This happens at the DATABASE level, not the application level:
  both writes occur in the same transaction. If either fails, both
  fail. Even a direct psql INSERT triggers the audit. There is no
  code path that can write these low-volume records without an audit
  trail.

WHY ONE GENERIC FUNCTION:
  Instead of a separate trigger function per table, we write one
  function that uses TG_TABLE_NAME and TG_OP (Postgres built-in
  variables) to know what triggered it.

WHY BIOSIGNALS ARE EXCLUDED:

  High-volume biosignal hypertables would generate millions of audit
  rows per long session. They are intentionally not trigger-audited
  here. Migration 026 creates biosignal_integrity_log for chunk-level
  write provenance, completeness, and tamper-evidence.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "020_audit_triggers"
down_revision: Union[str, None] = "019_session_signal_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Full audit: captures the entire row. One audit entry per INSERT row.
FULL_AUDIT_TABLES = [
    # Core clinical tables (001-011)
    "sessions",
    "alert_events",
    "echo_events",
    "session_feature_vectors",
    "session_notes",
    "schema_version_log",
    # Recording metadata (019)
    "session_signal_metadata",
]

def upgrade() -> None:
    # --- Full audit trigger function ---
    # Uses a PL/pgSQL variable (not a SQL CASE expression) to branch on
    # table name. SQL CASE evaluates all branch expressions at runtime even
    # when the condition is false, so NEW.session_id would fail for the
    # sessions table (which has no session_id column). IF/ELSE in PL/pgSQL
    # is genuinely lazy and only accesses the field that applies.
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_trigger_full_func()
        RETURNS TRIGGER AS $$
        DECLARE
            v_session_id UUID;
        BEGIN
            IF TG_TABLE_NAME = 'sessions' THEN
                v_session_id := NEW.id;
            ELSE
                v_session_id := NEW.session_id;
            END IF;

            INSERT INTO audit_events (
                session_id,
                event_type,
                table_name,
                record_id,
                payload,
                event_timestamp
            ) VALUES (
                v_session_id,
                TG_OP,
                TG_TABLE_NAME,
                NEW.id::TEXT,
                row_to_json(NEW)::jsonb,
                NOW()
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Attach full audit triggers (row-level)
    for table in FULL_AUDIT_TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_audit_trigger
            AFTER INSERT ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION audit_trigger_full_func();
        """)


def downgrade() -> None:
    for table in FULL_AUDIT_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit_trigger ON {table};")
    op.execute("DROP FUNCTION IF EXISTS audit_trigger_full_func;")
