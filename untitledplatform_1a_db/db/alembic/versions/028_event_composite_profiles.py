"""028 create ARC event composite profiles

Revision ID: 028_event_composite_profiles
Revises: 027_session_baselines
Create Date: 2026-05-12

WHY THIS TABLE EXISTS:
  event_composite_profiles is the durable ARC output table: one row per
  ECHO event per session that passes false discovery rate control.

  The table is mode-agnostic by design. Every row stores all three
  temporal window scales and the per-signal deviation metrics used to
  produce the profile, so later interpretation modes can read the same
  source record without rewriting or collapsing ARC output.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "028_event_composite_profiles"
down_revision: Union[str, None] = "027_session_baselines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE event_composite_profiles (
            id                          UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id                  UUID             NOT NULL,
            participant_id              UUID             NOT NULL,
            site_id                     UUID             NOT NULL,
            sponsor_id                  UUID             NOT NULL,
            echo_event_id               BIGINT           NOT NULL REFERENCES echo_events(id),

            w1_convergence_density      DOUBLE PRECISION NOT NULL CHECK (w1_convergence_density >= 0.0),
            w2_convergence_density      DOUBLE PRECISION NOT NULL CHECK (w2_convergence_density >= 0.0),
            w3_convergence_density      DOUBLE PRECISION NOT NULL CHECK (w3_convergence_density >= 0.0),
            w1_participating_signals    JSONB            NOT NULL DEFAULT '[]'::jsonb
                                                        CHECK (jsonb_typeof(w1_participating_signals) = 'array'),
            w2_participating_signals    JSONB            NOT NULL DEFAULT '[]'::jsonb
                                                        CHECK (jsonb_typeof(w2_participating_signals) = 'array'),
            w3_participating_signals    JSONB            NOT NULL DEFAULT '[]'::jsonb
                                                        CHECK (jsonb_typeof(w3_participating_signals) = 'array'),
            deviation_metrics           JSONB            NOT NULL DEFAULT '{}'::jsonb
                                                        CHECK (jsonb_typeof(deviation_metrics) = 'object'),

            null_threshold              DOUBLE PRECISION NOT NULL CHECK (
                                                        null_threshold >= 0.0 AND null_threshold <= 1.0
                                                    ),
            fdr_q_value                 DOUBLE PRECISION NOT NULL CHECK (
                                                        fdr_q_value >= 0.0 AND fdr_q_value <= 1.0
                                                    ),
            passed_fdr                  BOOLEAN          NOT NULL CHECK (passed_fdr IS TRUE),
            temporal_alignment_score    DOUBLE PRECISION CHECK (
                                                        temporal_alignment_score IS NULL OR
                                                        (
                                                            temporal_alignment_score >= 0.0 AND
                                                            temporal_alignment_score <= 1.0
                                                        )
                                                    ),
            sap_available_signals       JSONB            NOT NULL DEFAULT '[]'::jsonb
                                                        CHECK (jsonb_typeof(sap_available_signals) = 'array'),
            sap_participating_signals   JSONB            NOT NULL DEFAULT '[]'::jsonb
                                                        CHECK (jsonb_typeof(sap_participating_signals) = 'array'),
            arc_config_version          TEXT             NOT NULL,
            created_at                  TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

            CONSTRAINT event_composite_profiles_session_echo_event_unique
                UNIQUE (session_id, echo_event_id)
        );
    """)

    op.execute("""
        CREATE INDEX event_composite_profiles_session_idx
            ON event_composite_profiles (session_id, created_at DESC);
    """)
    op.execute("""
        CREATE INDEX event_composite_profiles_echo_event_idx
            ON event_composite_profiles (echo_event_id);
    """)
    op.execute("""
        CREATE INDEX event_composite_profiles_tenancy_idx
            ON event_composite_profiles (sponsor_id, site_id, session_id);
    """)
    op.execute("""
        CREATE INDEX event_composite_profiles_arc_config_idx
            ON event_composite_profiles (arc_config_version);
    """)

    op.execute("REVOKE UPDATE, DELETE ON event_composite_profiles FROM PUBLIC;")
    op.execute("""
        CREATE TRIGGER event_composite_profiles_audit_trigger
        AFTER INSERT ON event_composite_profiles
        FOR EACH ROW
        EXECUTE FUNCTION audit_trigger_full_func();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TRIGGER IF EXISTS event_composite_profiles_audit_trigger
        ON event_composite_profiles;
    """)
    op.execute("DROP TABLE IF EXISTS event_composite_profiles;")
