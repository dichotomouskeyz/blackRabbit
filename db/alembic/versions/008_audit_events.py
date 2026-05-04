"""008 create audit_events table

Revision ID: 008_audit_events
Revises: 007_respiration_samples
Create Date: 2026-04-26

WHY APPEND-ONLY:
  21 CFR Part 11 requires that electronic records used in clinical
  trials are tamper-evident. "Append-only" means:
    - Rows can be INSERTed, never UPDATEd or DELETEd.
    - Application code cannot write here directly — only database
      triggers can (enforced in Migration 012).
    - Every write to ANY other table automatically generates an
      audit_events row via trigger.

  This means if the FDA asks "prove that this EEG sample wasn't
  modified after the session," you can show the audit trail: the
  original INSERT event with its timestamp, and no subsequent
  UPDATE or DELETE events for that row.

WHY PAYLOAD IS JSONB:
  Audit events cover everything — session starts, config snapshots,
  device connections, biosignal writes, alert triggers, coordinator
  actions. Each event type has different data. JSONB handles this
  without needing 50 nullable columns.

  JSONB (not JSON) because JSONB is stored in a decomposed binary
  format that's queryable and indexable. JSON is stored as raw text
  and re-parsed on every query. Always use JSONB in Postgres.

WHY TWO TIMESTAMP COLUMNS:
  event_timestamp = when the event actually happened (may be an
  LSL timestamp or application timestamp).
  db_insert_time = when the audit row was written to the database.
  Same logic as biosignal tables — regulatory requirement.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "008_audit_events"
down_revision: Union[str, None] = "007_respiration_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_events (
            id              BIGSERIAL   PRIMARY KEY,
            session_id      TEXT,
            event_type      TEXT        NOT NULL,
            table_name      TEXT,
            record_id       TEXT,
            actor_id        TEXT,
            payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            db_insert_time  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Revoke UPDATE and DELETE from all roles on this table.
        -- Only INSERT is allowed. This is enforced at the database level,
        -- not just the application level — so even if someone connects
        -- via psql directly, they can't modify or delete audit rows.
        REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC;
    """)



def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_events;")
