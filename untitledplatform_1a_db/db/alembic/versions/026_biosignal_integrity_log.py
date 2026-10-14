"""026 create biosignal integrity and XDF reconciliation log

Revision ID: 026_biosignal_integrity_log
Revises: 025_clock_drift_log
Create Date: 2026-05-08

WHAT CHANGES AND WHY:

  eeg_samples, hrv_samples, eda_samples, and respiration_samples are
  high-volume hypertables. EEG at 250 Hz in narrow-row format (1 row
  per channel per sample, 8 channels) produces ~2,000 rows per second.
  Per-row audit triggers would produce ~57.6 million audit rows for EEG
  alone in an 8-hour session. That is operationally unsustainable.

  Raw biosignal samples are immutable append-only writes. What matters
  for the open-source 1a data foundation is:
    (a) proof the pipeline was actively writing during the session
    (b) tamper-evidence: detecting if stored values are later altered
    (c) completeness: watermark_verified + XDF reconciliation (024)

  This migration creates biosignal_integrity_log. The hash computation
  and log writes happen in lsl_forwarder after each successful chunk
  INSERT — one integrity row per chunk per modality. Session close
  reconciliation also writes a summary row into the same table so XDF
  reconciliation history stays colocated with the raw chunk integrity
  trail. TimescaleDB's transparent decompression path does not expose
  the xmin system column to trigger functions, making statement-level
  triggers with xmin filtering unreliable on hypertables.
  Application-level writes to biosignal_integrity_log are correct here:
  this is a technical integrity log, not the trigger-owned event trail.

  Full per-row audit triggers on all core governance tables — sessions,
  alert_events, echo_events, session_signal_metadata, etc. — are NOT
  touched by this migration.

HASH CONSTRUCTION (in lsl_forwarder, per chunk):
  EEG:         md5( sorted( sample_index | channel_id | voltage ) )
  HRV:         md5( sorted( sample_index | rr_interval_ms ) )
  EDA:         md5( sorted( sample_index | raw_conductance_us ) )
  Respiration: md5( sorted( sample_index | raw_amplitude ) )

  Sorted by sample_index (+ channel_id for EEG) so the hash is
  deterministic regardless of write order.  Including signal values
  means any post-hoc alteration to stored readings is detectable.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "026_biosignal_integrity_log"
down_revision: Union[str, None] = "025_clock_drift_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create biosignal_integrity_log — chunk integrity rows plus reconciliation summaries
    op.execute("""
        CREATE TABLE IF NOT EXISTS biosignal_integrity_log (
            id                  BIGSERIAL       PRIMARY KEY,
            session_id          UUID            NOT NULL,
            participant_id      UUID            NOT NULL,
            site_id             UUID            NOT NULL,
            sponsor_id          UUID            NOT NULL,
            log_type            TEXT            NOT NULL DEFAULT 'chunk_integrity',
            table_name          TEXT,
            row_count           INTEGER,
            min_sample_index    BIGINT,
            max_sample_index    BIGINT,
            chunk_hash          TEXT,
            hash_method         TEXT,
            reconciliation_report JSONB,
            written_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            CHECK (log_type IN ('chunk_integrity', 'xdf_reconciliation')),
            CHECK (
                (
                    log_type = 'chunk_integrity'
                    AND table_name IS NOT NULL
                    AND row_count IS NOT NULL
                    AND min_sample_index IS NOT NULL
                    AND max_sample_index IS NOT NULL
                    AND chunk_hash IS NOT NULL
                    AND hash_method IS NOT NULL
                    AND reconciliation_report IS NULL
                )
                OR (
                    log_type = 'xdf_reconciliation'
                    AND table_name IS NULL
                    AND row_count IS NULL
                    AND min_sample_index IS NULL
                    AND max_sample_index IS NULL
                    AND chunk_hash IS NULL
                    AND hash_method IS NULL
                    AND reconciliation_report IS NOT NULL
                )
            )
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS biosignal_integrity_log_session_idx
            ON biosignal_integrity_log (session_id, written_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS biosignal_integrity_log;")
