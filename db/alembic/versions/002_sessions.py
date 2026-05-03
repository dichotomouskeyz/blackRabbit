"""002 create sessions table

Revision ID: 002_sessions
Revises: 001_extensions
Create Date: 2026-04-26

WHY A POSTGRES ENUM FOR STATUS (NOT A TEXT CHECK CONSTRAINT):
  A Postgres ENUM is a first-class type. Valid values are stored in the
  system catalog, visible in schema browsers, and adding a new value is
  a simple ALTER TYPE ... ADD VALUE — no table rewrite required. A TEXT
  CHECK constraint requires an ALTER TABLE to change the constraint,
  which rewrites validation logic for every existing row and doesn't
  self-document in the schema.

  The tradeoff: ENUM values are harder to remove than to add. For session
  status, the values are stable and well-understood, so ENUM is correct.

WHY BATCH_PROCESSED_AT:
  When post-session batch completes (after watermark_verified is written),
  batch_processed_at is set. NULL = batch has not run. Non-NULL = batch
  completed at this timestamp. This is both the handoff signal from the
  streaming phase to the batch phase, and a regulatory requirement: you
  must be able to prove that post-session processing completed and when.

STATUS FLOW:
  initializing → active → closing → closed (normal path)
                        → failed   (error path)
  closed → batch_processed_at set (batch complete)

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

WHY CONSTRAINED UNITS:
  Free-text units are a data integrity disaster — "MG", "milligrams",
  "mg." are all different strings that mean the same thing. A CHECK
  constraint enforces a closed vocabulary at the database level so
  the batch layer, safety monitor, and any downstream analysis can
  rely on exact string matching without normalization.

  Allowed units:
    mg      — milligrams         (psilocybin, MDMA, ibogaine typical)
    ug      — micrograms ASCII   (LSD typical; ASCII-safe alias)
    µg      — micrograms Unicode (same unit, Unicode form)
    mg/kg   — weight-adjusted mg (dose-finding arms)
    ug/kg   — weight-adjusted µg (ASCII-safe)
    µg/kg   — weight-adjusted µg (Unicode form)

WHY room_id:
  The physical room in which a session takes place is a clinical
  variable — room acoustics, lighting, and physical layout are all
  protocol-defined environmental conditions. room_id links to the
  site's room registry, allowing analysis of whether environmental
  factors correlate with outcomes. It is site-scoped (a room_id is
  only meaningful within a given site_id).

WHY INDEXES ON sponsor_id, site_id, protocol_arm:
  Every API query filters by sponsor_id (regulatory requirement —
  no cross-sponsor data leakage). site_id is the next most common
  filter for site-level dashboards. protocol_arm (the trial arm, e.g.
  'high_dose_psilocybin', 'placebo') is the primary grouping variable
  for efficacy analysis. Indexing these independently also covers
  composite queries via index intersection.

  All sessions indexes are defined in 011_indexes.py, not here.

WHY updated_at TRIGGER:
  updated_at must reflect the actual time of the last change, not
  the time application code thinks it made a change. A database
  trigger is the only way to guarantee this — application code can
  forget to set it, be bypassed by direct DB access, or set it to
  the wrong value. The trigger fires on every UPDATE row, always.
  This is distinct from audit_events (which tracks WHAT changed);
  updated_at tracks WHEN the row was last touched.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "002_sessions"
down_revision: Union[str, None] = "001_extensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE session_status AS ENUM (
            'initializing',
            'active',
            'paused',
            'closing',
            'closed',
            'failed'
        );
    """)

    op.execute("""
        CREATE TABLE sessions (
            id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            site_id             UUID            NOT NULL,
            sponsor_id          UUID            NOT NULL,
            participant_id      UUID            NOT NULL,
            room_id             UUID,
            protocol_arm        TEXT,
            compound            TEXT            NOT NULL,
            compound_dose       DOUBLE PRECISION,
            compound_dose_unit  TEXT
                                CHECK (compound_dose_unit IN (
                                    'mg', 'ug', 'µg',
                                    'mg/kg', 'ug/kg', 'µg/kg'
                                )),
            therapist_id        TEXT,
            status              session_status  NOT NULL DEFAULT 'initializing',
            batch_processed_at  TIMESTAMPTZ,
            started_at          TIMESTAMPTZ,
            closed_at           TIMESTAMPTZ,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        );

        -- Trigger function: sets updated_at = NOW() on every UPDATE.
        -- Named generically so it can be reused by other tables in later
        -- migrations without redefining it.
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER sessions_set_updated_at
        BEFORE UPDATE ON sessions
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TRIGGER IF EXISTS sessions_set_updated_at ON sessions;
        DROP FUNCTION IF EXISTS set_updated_at();
        DROP TABLE IF EXISTS sessions;
        DROP TYPE IF EXISTS session_status;
    """)
