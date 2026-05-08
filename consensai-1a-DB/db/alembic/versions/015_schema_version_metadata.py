"""015 add schema version metadata

Revision ID: 015_schema_version_metadata
Revises: 014_consent_log
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
  - app_version: the Consensai application version (semver string,
    e.g., "1.0.0-alpha"). Set via APP_VERSION env var.
  - python_version: sys.version at session start
  - postgres_version: SELECT version() at session start
  - timescaledb_version: SELECT extversion FROM pg_extension
  - pgvector_version: same pg_extension query, extension name 'vector'
  - mne_version: mne.__version__
  - neurokit2_version: neurokit2.__version__
  - pylsl_version: pylsl.__version__
  - recorded_at: when the version snapshot was taken

WHY ALL THESE VERSIONS:
  Every component in this stack can affect the values computed from a
  session's raw biosignal data. MNE's ICA implementation changed
  behavior between minor versions. Neurokit2's HRV feature names were
  renamed across versions. TimescaleDB's compression behavior affects
  how data is stored and queried. pgvector's distance functions evolved.

  Without knowing the exact version of every component at session time,
  you cannot reproduce a batch computation from raw data alone — which
  is a regulatory requirement for an IND. These columns are the
  computational provenance record for every session.

HOW IT WORKS:
  session_init.py (Phase 2) writes one row to this table at session
  start, alongside the config_snapshot audit event. It reads the
  current Alembic head and the APP_VERSION env var automatically.

  This means every session has a permanent record of exactly what
  version of the system created it.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "015_schema_version_metadata"
down_revision: Union[str, None] = "014_consent_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE schema_version_log (
            id                   BIGSERIAL   PRIMARY KEY,
            session_id           UUID        NOT NULL,
            site_id              UUID        NOT NULL,
            sponsor_id           UUID        NOT NULL,
            alembic_version      TEXT        NOT NULL,
            app_version          TEXT        NOT NULL,
            python_version       TEXT,
            postgres_version     TEXT,
            timescaledb_version  TEXT,
            pgvector_version     TEXT,
            mne_version          TEXT,
            neurokit2_version    TEXT,
            pylsl_version        TEXT,
            recorded_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    # session_init.py reads os.getenv("APP_VERSION", "unknown") and
    # writes it to this table at session start.


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schema_version_log;")
