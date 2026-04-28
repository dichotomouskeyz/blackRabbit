"""006 create sessions table

Revision ID: 006_sessions
Revises: 005_respiration_samples
Create Date: 2026-04-26

WHY THIS IS A REGULAR TABLE (NOT A HYPERTABLE):
  Sessions are low-volume (maybe 5 per day at peak), relationally
  queried (JOIN to biosignal tables), and need full ACID guarantees.
  Hypertables are optimized for high-throughput append-only writes —
  the opposite of what sessions need.

WHY PARTICIPANT_ID IS PSEUDONYMOUS:
  Real participant identity (name, DOB, contact info) lives at the
  clinical site and NEVER enters Consensai's database. What we store
  is a site-generated pseudonymous ID (e.g., "SITE01-P042"). The
  mapping between pseudonymous ID and real identity is maintained
  by the site's own systems — we never see it.

  This is both a HIPAA requirement and an architectural decision:
  if Consensai's database were breached, no real identities are
  exposed because they were never there.

WHY COMPOUND_DOSE AND COMPOUND_DOSE_UNIT ARE SEPARATE:
  "5mg" as a single string is unparseable. "5" + "mg" as separate
  columns lets you query "show me all sessions above 3mg" without
  string parsing. compound_dose_unit also distinguishes mg vs µg —
  critical for LSD where typical doses are in micrograms.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006_sessions"
down_revision: Union[str, None] = "005_respiration_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sessions (
            id              TEXT        PRIMARY KEY,
            site_id         TEXT        NOT NULL,
            sponsor_id      TEXT        NOT NULL,
            participant_id  TEXT        NOT NULL,
            protocol_arm    TEXT,
            compound        TEXT        NOT NULL,
            compound_dose   DOUBLE PRECISION,
            compound_dose_unit TEXT,
            therapist_id    TEXT,
            status          TEXT        NOT NULL DEFAULT 'initializing'
                            CHECK (status IN (
                                'initializing',
                                'active',
                                'paused',
                                'closing',
                                'closed',
                                'failed'
                            )),
            started_at      TIMESTAMPTZ,
            closed_at       TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions;")
