"""018 add schema version metadata

Revision ID: 018_schema_version_metadata
Revises: 017_consent_log
Create Date: 2026-04-27

WHY SCHEMA VERSION METADATA:
  Consensai will evolve. Migrations will be added. New columns will
  appear. Features will change. Over the course of a clinical trial
  spanning months or years, the schema at session 1 may be different
  from the schema at session 200.

  For longitudinal analysis, the batch layer and intelligence layer
  must know WHICH version of the schema was in place when a given
  session was recorded. Otherwise:
    - Features computed from session 1 data may not match features
      computed from session 200 data if the underlying schema changed
    - Debugging anomalies in old sessions requires knowing what the
      system looked like at the time

  This is also a regulatory requirement: you must be able to
  reconstruct the exact state of the system at the time of any
  recorded data. Schema version is part of that reconstruction.

WHAT GETS RECORDED:
  - alembic_version: the migration head at session creation time
    (e.g., "018_schema_version_metadata")
  - app_version: the Consensai application version (semver string,
    e.g., "1.0.0-alpha"). Set via APP_VERSION env var.
  - recorded_at: when the version snapshot was taken

HOW IT WORKS:
  session_init.py (Phase 2) writes one row to this table at session
  start, alongside the config_snapshot audit event. It reads the
  current Alembic head and the APP_VERSION env var automatically.

  This means every session has a permanent record of exactly what
  version of the system created it.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "016_schema_version_metadata"
down_revision: Union[str, None] = "015_consent_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE schema_version_log (
            id              BIGSERIAL   PRIMARY KEY,
            session_id      TEXT        NOT NULL,
            site_id         TEXT        NOT NULL,
            sponsor_id      TEXT        NOT NULL,
            alembic_version TEXT        NOT NULL,
            app_version     TEXT        NOT NULL,
            python_version  TEXT,
            recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("""
        CREATE INDEX idx_schema_version_session
        ON schema_version_log (session_id);
    """)

    op.execute("""
        CREATE INDEX idx_schema_version_alembic
        ON schema_version_log (alembic_version);
    """)

    op.execute("""
        CREATE INDEX idx_schema_version_recorded
        ON schema_version_log (recorded_at DESC);
    """)

    # Also add APP_VERSION to .env — document it here as a reminder.
    # session_init.py reads os.getenv("APP_VERSION", "unknown") and
    # writes it to this table at session start.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schema_version_log;")
