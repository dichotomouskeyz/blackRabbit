"""027 create ARC session baselines

Revision ID: 027_session_baselines
Revises: 026_biosignal_integrity_log
Create Date: 2026-05-12

WHY THIS TABLE EXISTS:
  ARC needs persisted baseline values to interpret post-session signal
  deviations. Each analysis run preserves its baseline estimates, units,
  extractor version and configuration/input hashes after capture verification.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "027_session_baselines"
down_revision: Union[str, None] = "026_biosignal_integrity_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE session_baselines (
            analysis_id                 UUID             NOT NULL,
            session_id                  UUID             NOT NULL,
            participant_id              UUID             NOT NULL,
            site_id                     UUID             NOT NULL,
            sponsor_id                  UUID             NOT NULL,
            modality                    TEXT             NOT NULL,
            signal_component            TEXT             NOT NULL,
            baseline_mean               DOUBLE PRECISION NOT NULL,
            baseline_std                DOUBLE PRECISION NOT NULL CHECK (baseline_std >= 0.0),
            baseline_window_start       DOUBLE PRECISION NOT NULL,
            baseline_window_end         DOUBLE PRECISION NOT NULL,
            sample_count                INTEGER          NOT NULL CHECK (sample_count > 0),
            epoch_count                 INTEGER          NOT NULL CHECK (epoch_count >= 2),
            units                       TEXT             NOT NULL,
            extractor_version           TEXT             NOT NULL,
            config_version              TEXT             NOT NULL,
            config_sha256               TEXT             NOT NULL CHECK (length(config_sha256) = 64),
            input_sha256                TEXT             NOT NULL CHECK (length(input_sha256) = 64),
            created_at                  TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

            PRIMARY KEY (analysis_id, modality, signal_component),
            CONSTRAINT session_baselines_modality_check
                CHECK (modality IN ('eeg', 'hrv', 'eda', 'respiration')),
            CONSTRAINT session_baselines_window_order_check
                CHECK (baseline_window_end > baseline_window_start)
        );
    """)

    op.execute("""
        CREATE INDEX session_baselines_session_idx
            ON session_baselines (session_id);
    """)
    op.execute("""
        CREATE INDEX session_baselines_tenancy_idx
            ON session_baselines (sponsor_id, site_id, session_id);
    """)
    op.execute("""
        CREATE INDEX session_baselines_modality_component_idx
            ON session_baselines (modality, signal_component);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS session_baselines;")
