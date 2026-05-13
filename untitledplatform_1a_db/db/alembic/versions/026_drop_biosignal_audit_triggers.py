"""026 replace per-row biosignal audit triggers with chunk-level integrity log

Revision ID: 026_biosignal_integrity_log
Revises: 025_clock_drift_log
Create Date: 2026-05-08

WHAT CHANGES AND WHY:

  The per-row lightweight audit triggers on eeg_samples, hrv_samples,
  eda_samples, and respiration_samples (migration 020) fire once per
  row written.  EEG at 250 Hz in narrow-row format (1 row per channel
  per sample, 8 channels) produces ~2,000 audit rows per second.
  An 8-hour ibogaine session would generate ~57.6 million audit rows
  for EEG alone.  That is operationally unsustainable.

  21 CFR Part 11 audit trails apply to mutable governance records —
  who changed what and when.  Raw biosignal samples are immutable
  append-only writes.  What matters regulatorily is:
    (a) proof the pipeline was actively writing during the session
    (b) tamper-evidence: detecting if stored values are later altered
    (c) completeness: watermark_verified + XDF reconciliation (024)

  This migration creates biosignal_integrity_log and drops the old
  per-row lightweight triggers.  The hash computation and log writes
  happen in lsl_forwarder after each successful chunk INSERT — one
  integrity row per chunk per modality.  TimescaleDB's transparent
  decompression path does not expose the xmin system column to trigger
  functions, making statement-level triggers with xmin filtering
  unreliable on hypertables.  Application-level writes to
  biosignal_integrity_log are correct here: this is a technical
  integrity log, not a regulatory audit trail (that is audit_events,
  which remains trigger-only per 21 CFR Part 11).

  Full per-row audit triggers on all governance tables — sessions,
  alert_events, echo_events, session_signal_metadata, consent_log,
  electronic_signatures, investigational_product_log,
  adverse_event_log, etc. — are NOT touched by this migration.

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

_BIOSIGNAL_TABLES = ["eeg_samples", "hrv_samples", "eda_samples", "respiration_samples"]


def upgrade() -> None:
    # Drop old per-row lightweight triggers and function
    for table in _BIOSIGNAL_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit_trigger ON {table};")
    op.execute("DROP FUNCTION IF EXISTS audit_trigger_lightweight_func;")

    # Create biosignal_integrity_log — written by lsl_forwarder, one row per chunk
    op.execute("""
        CREATE TABLE IF NOT EXISTS biosignal_integrity_log (
            id                  BIGSERIAL       PRIMARY KEY,
            session_id          UUID            NOT NULL,
            site_id             UUID            NOT NULL,
            sponsor_id          UUID            NOT NULL,
            table_name          TEXT            NOT NULL,
            row_count           INTEGER         NOT NULL,
            min_sample_index    BIGINT          NOT NULL,
            max_sample_index    BIGINT          NOT NULL,
            chunk_hash          TEXT            NOT NULL,
            written_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS biosignal_integrity_log_session_idx
            ON biosignal_integrity_log (session_id, written_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS biosignal_integrity_log;")

    op.execute("""
        CREATE OR REPLACE FUNCTION audit_trigger_lightweight_func()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO audit_events (
                session_id, event_type, table_name, record_id, payload, event_timestamp
            ) VALUES (
                NEW.session_id, TG_OP, TG_TABLE_NAME, NEW.id::TEXT,
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
    for table in _BIOSIGNAL_TABLES:
        op.execute(f"""
            CREATE TRIGGER {table}_audit_trigger
            AFTER INSERT ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION audit_trigger_lightweight_func();
        """)
