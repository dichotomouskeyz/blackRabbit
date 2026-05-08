"""024 sessions watermark trigger

Adds an AFTER UPDATE trigger on sessions that writes to audit_events when
status transitions to 'closed' (watermark_verified) or 'failed'
(watermark_failed).  The event_type names are the gate that batch processing
checks before running post-session jobs.

Revision ID: 024_watermark_trigger
Revises: 023_indexes
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "024_watermark_trigger"
down_revision: Union[str, None] = "023_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION sessions_watermark_func()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Only act on genuine status transitions.
            IF NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;

            IF NEW.status = 'closed' THEN
                INSERT INTO audit_events (
                    session_id,
                    event_type,
                    table_name,
                    record_id,
                    payload,
                    event_timestamp
                ) VALUES (
                    NEW.id,
                    'watermark_verified',
                    'sessions',
                    NEW.id::TEXT,
                    jsonb_build_object(
                        'old_status', OLD.status::TEXT,
                        'new_status', NEW.status::TEXT,
                        'closed_at',  NEW.closed_at
                    ),
                    NOW()
                );

            ELSIF NEW.status = 'failed' THEN
                INSERT INTO audit_events (
                    session_id,
                    event_type,
                    table_name,
                    record_id,
                    payload,
                    event_timestamp
                ) VALUES (
                    NEW.id,
                    'watermark_failed',
                    'sessions',
                    NEW.id::TEXT,
                    jsonb_build_object(
                        'old_status', OLD.status::TEXT,
                        'new_status', NEW.status::TEXT,
                        'closed_at',  NEW.closed_at
                    ),
                    NOW()
                );
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER sessions_watermark_trigger
        AFTER UPDATE ON sessions
        FOR EACH ROW
        EXECUTE FUNCTION sessions_watermark_func();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS sessions_watermark_trigger ON sessions;")
    op.execute("DROP FUNCTION IF EXISTS sessions_watermark_func();")
