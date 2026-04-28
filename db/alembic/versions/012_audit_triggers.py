"""012 create audit triggers on all tables

Revision ID: 012_audit_triggers
Revises: 011_pgvector_columns
Create Date: 2026-04-26

HOW TRIGGERS WORK:
  A database trigger is a function that Postgres runs automatically
  when a specific event happens on a table. Here, we're saying:
  "every time ANY row is INSERTed into ANY of our tables, also
  INSERT a row into audit_events describing what just happened."

  This happens at the DATABASE level, not the application level.
  This distinction is critical:

  Application-level logging: your Python code writes to the table,
  then separately writes to the audit table. If the app crashes
  between those two writes, you have data with no audit trail.
  Also, any direct psql connection bypasses your app entirely.

  Database-level triggers: Postgres itself handles both writes in
  the same transaction. If either fails, both fail. Even a direct
  psql INSERT triggers the audit. There is no code path that can
  write data without an audit trail.

WHY ONE GENERIC FUNCTION:
  Instead of writing a separate trigger function per table, we write
  ONE function (audit_trigger_func) that uses TG_TABLE_NAME and
  TG_OP (Postgres built-in variables) to know which table and
  what operation triggered it. Then we attach that one function
  to every table. Less code, less maintenance, same coverage.

WHAT NEW.* IS:
  In a trigger function, NEW refers to the row being inserted.
  NEW.id is the ID of the new row, NEW.session_id is its session_id,
  etc. We use row_to_json(NEW) to capture the entire new row as
  JSONB in the audit payload.

  For biosignal tables (millions of rows), we DON'T store the full
  row in the audit payload — just the identifying info. Storing
  every EEG sample twice would double storage. The audit trail for
  biosignals records THAT a write happened, not the full data.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "012_audit_triggers"
down_revision: Union[str, None] = "011_pgvector_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables where we audit the full row content (low-volume tables)
FULL_AUDIT_TABLES = [
    "sessions",
    "alert_events",
    "humen_events",
    "voice_segments",
    "session_feature_vectors",
    "session_notes",
]

# Tables where we audit only metadata (high-volume biosignal tables)
# Full row would double storage for millions of rows
LIGHTWEIGHT_AUDIT_TABLES = [
    "eeg_samples",
    "hrv_samples",
    "eda_samples",
    "respiration_samples",
]


def upgrade() -> None:
    # --- Full audit trigger function (for low-volume tables) ---
    # Captures the entire new row as JSONB in the audit payload.
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_trigger_full_func()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO audit_events (
                session_id,
                event_type,
                table_name,
                record_id,
                payload,
                event_timestamp
            ) VALUES (
                -- Try to get session_id from the new row; NULL if not present
                CASE
                    WHEN TG_TABLE_NAME = 'sessions' THEN NEW.id
                    ELSE NEW.session_id
                END,
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

    # --- Lightweight audit trigger function (for high-volume tables) ---
    # Only records that the write happened, not the full row data.
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_trigger_lightweight_func()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO audit_events (
                session_id,
                event_type,
                table_name,
                record_id,
                payload,
                event_timestamp
            ) VALUES (
                NEW.session_id,
                TG_OP,
                TG_TABLE_NAME,
                NEW.id::TEXT,
                jsonb_build_object(
                    'sample_index', NEW.sample_index,
                    'lsl_timestamp', NEW.lsl_timestamp,
                    'device_id', NEW.device_id
                ),
                NOW()
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Attach full audit triggers to low-volume tables
    for table in FULL_AUDIT_TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_audit_trigger
            AFTER INSERT ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION audit_trigger_full_func();
        """)

    # Attach lightweight audit triggers to high-volume tables
    for table in LIGHTWEIGHT_AUDIT_TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_audit_trigger
            AFTER INSERT ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION audit_trigger_lightweight_func();
        """)


def downgrade() -> None:
    all_tables = FULL_AUDIT_TABLES + LIGHTWEIGHT_AUDIT_TABLES
    for table in all_tables:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit_trigger ON {table};")
    op.execute("DROP FUNCTION IF EXISTS audit_trigger_full_func;")
    op.execute("DROP FUNCTION IF EXISTS audit_trigger_lightweight_func;")
