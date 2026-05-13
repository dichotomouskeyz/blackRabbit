"""025 create clock_drift_log table

Revision ID: 025_clock_drift_log
Revises: 024_watermark_trigger
Create Date: 2026-05-08

WHY A DEDICATED TABLE:
  LSL (Lab Streaming Layer) uses its own clock that drifts relative to
  NTP / wall clock over time. inlet.time_correction() returns the offset
  in seconds needed to align LSL timestamps with network time.

  For short psilocybin/MDMA sessions (4–6 hours) drift is a footnote.
  For ibogaine sessions (8+ hours) drift accumulates — up to tens of
  milliseconds over the session — and must be recoverable post-hoc so
  the batch layer can apply time-alignment corrections.

  Storing drift in the log file is insufficient: rotating log files can
  be lost, truncated, or be on a different filesystem from the DB backup.
  The DB is the durable record. This table gives reviewers and the batch
  layer a queryable, session-scoped audit trail of device clock behavior.

WHY NOT session_signal_metadata:
  session_signal_metadata holds a single row per (session_id, modality) —
  it captures the static recording setup, not time-series observations.
  Clock drift is an ongoing per-stream observation, sampled every
  CLOCK_DRIFT_RECORD_INTERVAL seconds (default 60 s). It is fundamentally
  different in cardinality and mutability from recording-setup metadata.

WHY exceeds_threshold AND threshold_s:
  The threshold can change between deployments (set via .env). Storing
  the threshold at measurement time means a post-hoc reviewer can always
  reconstruct exactly which measurements were flagged at the time they
  were recorded, even if the threshold has since been reconfigured.

WHY lsl_timestamp (not just db_insert_time):
  Follows the same two-timestamp rule as every other table: lsl_timestamp
  is WHEN the device's clock was sampled; db_insert_time is WHEN the row
  was committed. These will never be equal — the call to time_correction()
  and the DB write are separated by at least one RTT.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "025_clock_drift_log"
down_revision: Union[str, None] = "024_watermark_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE clock_drift_log (
            id                      BIGSERIAL       PRIMARY KEY,
            session_id              UUID            NOT NULL,
            participant_id          UUID            NOT NULL,
            site_id                 UUID            NOT NULL,
            sponsor_id              UUID            NOT NULL,
            device_id               UUID            NOT NULL,
            stream_type             TEXT            NOT NULL
                                    CHECK (stream_type IN (
                                        'EEG', 'HRV', 'EDA', 'Respiration'
                                    )),
            remote_clock_offset_s   DOUBLE PRECISION NOT NULL,
            exceeds_threshold       BOOLEAN         NOT NULL,
            threshold_s             DOUBLE PRECISION NOT NULL,
            lsl_timestamp           DOUBLE PRECISION NOT NULL,
            db_insert_time          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        );

        CREATE INDEX idx_clock_drift_session
            ON clock_drift_log (session_id, stream_type, db_insert_time DESC);

        CREATE INDEX idx_clock_drift_tenancy
            ON clock_drift_log (sponsor_id, site_id, db_insert_time DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS idx_clock_drift_tenancy;
        DROP INDEX IF EXISTS idx_clock_drift_session;
        DROP TABLE IF EXISTS clock_drift_log;
    """)
