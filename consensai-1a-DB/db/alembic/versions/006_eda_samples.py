"""006 create eda_samples hypertable

Revision ID: 006_eda_samples
Revises: 005_hrv_samples
Create Date: 2026-04-26

WHY EDA GETS ITS OWN TABLE:
  EDA (electrodermal activity / galvanic skin response) measures
  sweat gland activity via skin conductance. It's the primary
  autonomic arousal signal — when someone has an emotionally
  significant experience, EDA spikes within 1-4 seconds.

  For psychedelic sessions, EDA is the fastest autonomic indicator
  of subjective intensity. Combined with HRV and EEG, it forms
  the triangulation that makes Consensai's signal useful.

  Raw unit is microsiemens (µS). The batch layer (Neurokit2)
  decomposes the signal into tonic (baseline) and phasic
  (event-related) components post-session using cvxEDA.

WHY COMPOSITE PRIMARY KEY (id, session_id, lsl_timestamp, db_insert_time):
  Same rationale as hrv_samples — no channel dimension, UUID id
  provides global uniqueness, db_insert_time is required by
  TimescaleDB in all unique constraints on a partitioned hypertable.

--- RECORDING-LEVEL METADATA ---

WHY electrode_placement:
  EDA electrode placement is a first-class clinical variable, not
  device metadata. Palmar (fingers/palm), thenar (thumb base), and
  plantar (foot sole) placements produce systematically different
  baseline conductance values and arousal response magnitudes because
  sweat gland density and skin thickness differ across sites.
  cvxEDA and any normalization step in the batch layer must know
  placement to apply the correct reference ranges. Stored here rather
  than in device config because placement can change across sessions
  at the same site.

WHY electrode_type (Ag/AgCl vs dry):
  Wet Ag/AgCl electrodes have a far lower noise floor than dry
  electrodes — typically 0.001 µS vs 0.1 µS. This 100x difference
  changes the minimum detectable skin conductance response threshold.
  The SQI monitor and batch layer must know electrode type to apply
  the correct noise floor assumption. A dry electrode signal that
  looks "clean" may be masking small phasic responses that a wet
  electrode would have captured.

WHY skin_prep:
  Skin preparation before electrode placement is a legitimate clinical
  protocol variable — not housekeeping. Abrading the stratum corneum
  (the outer dead skin layer) reduces skin impedance by 10-100x,
  dramatically increasing signal amplitude and SNR. Cleaning with
  isopropyl alcohol removes oils and lowers contact resistance.
  Two sessions with identical electrodes and placement but different
  skin prep will produce non-comparable baseline conductance values.
  Required for cross-session normalization in the batch layer.

WHY signal_source (SCL vs SCR):
  Some research-grade EDA devices output the tonic (SCL — skin
  conductance level) and phasic (SCR — skin conductance response)
  components as separate hardware channels, having already applied
  an analog decomposition circuit. When this is the case, the raw
  combined signal is unavailable and cvxEDA must not be run again
  on what is already a decomposed output.
  'combined' = raw undecomposed signal (default; batch layer runs
  cvxEDA). 'scl' or 'scr' = device has already decomposed; batch
  layer skips cvxEDA for this stream.

WHY sample_rate_hz:
  EDA devices sample at widely different rates — 4 Hz (basic wearable)
  to 32 Hz (research-grade). cvxEDA's optimization uses sample rate
  to set the tonic/phasic time constants. The batch layer reads this
  column to configure Neurokit2 correctly rather than assuming a
  fixed rate.

WHY software_filters:
  EDA signals contain motion artifact, baseline drift, and high-freq
  noise. Filtering before storage changes the shape of the phasic
  component and therefore the cvxEDA decomposition output. Storing
  the exact filter chain — as a JSONB object of objects — makes the
  pipeline fully reproducible. Same contract as eeg_samples and
  hrv_samples: object-of-objects or "n/a".

WHY eda_range_us:
  Every EDA sensor has a rated measurement range in microsiemens
  (e.g., 0.01–100 µS for the Shimmer3 GSR+). Storing the declared
  range lets the SQI monitor flag samples near the hardware limit as
  potentially saturating without hardcoding device-specific values.

--- PER-SAMPLE SIGNAL DATA ---

WHY raw_conductance_us AND conductance_us ARE SEPARATE:
  raw_conductance_us is the direct hardware output — never touched
  by any filter or transform. conductance_us is what was stored after
  whatever software_filters were applied. Both are preserved because:
    1. Regulatory requirement: the original captured value must be
       recoverable even if a processing bug is later discovered.
    2. The batch layer may need to re-run filtering with different
       parameters; it needs the unprocessed source to do so.
  If no software filters were applied, both columns hold the same
  value. They must never be derived from each other at write time —
  raw_conductance_us comes directly from the device buffer.

WHY sqi_flag IS SMALLINT:
  Signal quality index — same pattern as hrv_samples and eeg_samples.
  Written by sqi_monitor.py post-capture; NULL until evaluated.
  Kept as a narrow integer (not JSONB) because the safety monitor
  filters on it with a simple inequality at high frequency.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006_eda_samples"
down_revision: Union[str, None] = "005_hrv_samples"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE eda_samples (
            id                      UUID        NOT NULL DEFAULT gen_random_uuid(),
            session_id              UUID        NOT NULL,
            participant_id          TEXT        NOT NULL,
            site_id                 TEXT        NOT NULL,
            sponsor_id              TEXT        NOT NULL,
            device_id               TEXT        NOT NULL,


            -- Per-sample signal data
            raw_conductance_us      FLOAT       NOT NULL,
            conductance_us          FLOAT       NOT NULL,
            signal_quality          FLOAT,
            lsl_timestamp           DOUBLE PRECISION NOT NULL,
            db_insert_time          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            sqi_flag                SMALLINT,
            sample_index            BIGINT      NOT NULL,

            PRIMARY KEY (id, session_id, lsl_timestamp, db_insert_time)
        );

        SELECT create_hypertable(
            'eda_samples',
            'db_insert_time',
            chunk_time_interval => INTERVAL '1 hour'
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eda_samples;")
