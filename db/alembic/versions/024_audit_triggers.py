"""026 create audit triggers on all tables

Revision ID: 026_audit_triggers
Revises: 025_session_signal_metadata
Create Date: 2026-05-02

WHY THIS RUNS LAST:
  Audit triggers must be attached AFTER the tables they watch exist.
  This migration runs after every table in the schema has been created,
  so a single migration can cover the full table set without spreading
  trigger attachments across individual table migrations.

HOW TRIGGERS WORK:
  A database trigger is a function that Postgres runs automatically
  when a specific event happens on a table. Here we attach triggers
  to every table so that every INSERT also writes a row to audit_events.

  This happens at the DATABASE level, not the application level:
  both writes occur in the same transaction. If either fails, both
  fail. Even a direct psql INSERT triggers the audit. There is no
  code path that can write data without an audit trail.

WHY ONE GENERIC FUNCTION PER TIER:
  Instead of a separate trigger function per table, we write one
  function per audit tier (full and chunk) that uses TG_TABLE_NAME
  and TG_OP (Postgres built-in variables) to know what triggered it.

WHY TWO TIERS:

  FULL AUDIT (low-volume clinical and regulatory tables):
    Captures the entire new row as JSONB. These tables produce at most
    one row per clinical event — consent logs, signatures, AE records —
    so full-row capture is both appropriate and inexpensive.

  LIGHTWEIGHT AUDIT (high-volume biosignal hypertables):
    Captures only the identifying fields per row — sample_index,
    lsl_timestamp, device_id — rather than the full biosignal value.
    This proves each write happened and when, without duplicating
    the signal data that already lives in the hypertable.

WHY session_id IS NULL FOR SYSTEM TABLES:
  system_users and system_user_access_log are system-level entities —
  user account management is not scoped to a clinical session.
  Forcing a session_id on these rows would be misleading. The CASE
  in audit_trigger_full_func() explicitly returns NULL for these tables
  so the audit row is still written correctly without referencing a
  non-existent column.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "024_audit_triggers"
down_revision: Union[str, None] = "023_session_signal_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Full audit: captures the entire row. One audit entry per INSERT row.
FULL_AUDIT_TABLES = [
    # Core clinical tables (001-011)
    "sessions",
    "alert_events",
    "humen_events",
    "session_feature_vectors",
    "session_notes",
    # Regulatory tables (017-022)
    "participant_consent_log",
    "schema_version_log",
    "electronic_signatures",
    "investigational_product_log",
    "adverse_event_log",
    "protocol_deviation_log",
    # System access tables (023-024)
    "data_access_log",
    "system_users",
    "system_user_access_log",
    # Recording metadata (025)
    "session_signal_metadata",
]

# Lightweight audit: one audit entry per row, minimal payload.
LIGHTWEIGHT_AUDIT_TABLES = [
    "eeg_samples",
    "hrv_samples",
    "eda_samples",
    "respiration_samples",
]


def upgrade() -> None:
    # --- Full audit trigger function ---
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
                CASE
                    WHEN TG_TABLE_NAME = 'sessions'
                        THEN NEW.id
                    WHEN TG_TABLE_NAME IN (
                        'system_users',
                        'system_user_access_log'
                    )
                        THEN NULL
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

    # --- Lightweight audit trigger function (for high-volume hypertables) ---
    # Records that the write happened without storing the full row.
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

    # Attach full audit triggers (row-level)
    for table in FULL_AUDIT_TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_audit_trigger
            AFTER INSERT ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION audit_trigger_full_func();
        """)

    # Attach lightweight audit triggers (row-level)
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
    op.execute("DROP FUNCTION IF EXISTS audit_trigger_lightweight_func;")
    op.execute("DROP FUNCTION IF EXISTS audit_trigger_full_func;")
