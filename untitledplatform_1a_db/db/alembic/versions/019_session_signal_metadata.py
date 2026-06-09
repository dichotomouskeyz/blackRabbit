"""019 create session_signal_metadata table

Revision ID: 019_session_signal_metadata
Revises: 015_schema_version_metadata
Create Date: 2026-05-02

WHY THIS TABLE EXISTS:
  Every biosignal sample table (eeg_samples, hrv_samples, eda_samples,
  respiration_samples) previously carried recording-level metadata on
  every row. Fields like eeg_reference, sampling_frequency, modality-specific
  electrode setup, and beat detection algorithm are constants — they describe
  how a recording was set up, not what the signal value was at a given
  moment.

  Duplicating constants across millions of rows is wrong for three
  reasons:
    1. Storage: a 4-hour EEG session at 256 Hz × 8 channels = ~29M rows.
       Storing a TEXT eeg_reference on each row copies the same 10 bytes
       29 million times.
    2. Consistency: if a coordinator corrects a metadata entry (e.g.,
       wrong electrode cap model entered at session start), you'd need to
       UPDATE millions of rows. That's a write that should update one row.
    3. Clarity: a schema reviewer looking at eeg_samples should see signal
       data. Recording provenance belongs in its own table, with its own
       event trail entry.

  session_signal_metadata holds exactly one row per (session_id, modality).
  The four sample hypertables hold only what varies per sample.

WHY capture_source:
  capture_source repeats the session-level signal origin on each modality row so
  downstream exports and ARC jobs can filter per-modality provenance without
  joining back to sessions. It records simulated vs hardware origin only; ingest
  provenance such as XDF backfill is tracked separately.

WHY (session_id, modality) AS PRIMARY KEY:
  session_id scopes a recording to a single clinical encounter.
  modality distinguishes the four biosignal streams. Together they
  uniquely identify one set of recording conditions. There is exactly
  one metadata record per stream per session — not one per device, not
  one per channel, not one per time window.

WHY A FLAT TABLE INSTEAD OF FOUR MODALITY-SPECIFIC TABLES:
  Four separate tables (eeg_recording_metadata, hrv_recording_metadata,
  etc.) would require four JOINs in any query that needs provenance
  for a multi-modality session export. A flat table with nullable
  modality-specific columns and a modality CHECK constraint keeps the
  JOIN simple: WHERE session_id = ? AND modality = 'eeg'.

  Null columns for non-applicable modalities are inert — they consume
  no storage in Postgres when NULL and impose no query overhead.
  The trade-off is a wider schema; the benefit is a single table and
  a single JOIN pattern for all four modalities.

WHY SHARED COLUMNS (software_filters, power_line_frequency, sample_rate_hz):
  Several recording-level concepts apply across more than one modality:
    software_filters — EEG, HRV, and EDA all describe their filter chains
      in JSONB. The same column is reused; the modality column provides
      context for interpreting it.
    power_line_frequency — EEG and HRV both require AC power frequency
      for notch filter configuration.
    sample_rate_hz — EDA and respiration both record their capture rate
      here.
  Sharing columns avoids three near-identical JSONB columns named
  eeg_software_filters, hrv_software_filters, eda_software_filters.

WHY software_filters IS JSONB (object-of-objects or "n/a"):
  The filter chain applied to a biosignal is a structured provenance
  artifact, not a free-text note. Storing it as JSONB lets the batch
  layer read and replay the exact filter parameters programmatically.
  The CHECK constraint enforces that the value is either:
    - A JSONB object (one key per filter, value = its parameters), OR
    - The JSON string "n/a" (no filters applied or information unavailable)
  A plain NULL means the field is not applicable for this modality
  (e.g., software_filters is NULL for a respiration row because
  respiration does not have a filter chain recorded here).

WHY EEG METADATA FIELDS:
  eeg_reference (TEXT): electrode reference scheme — e.g., 'average',
    'Cz', 'linked-mastoids'. Reference choice produces systematically
    different voltage values. MNE must know this to re-reference.
  eeg_sensor_form (TEXT): physical EEG collection form. A cap, individual
    cup electrodes, and a dry headset all have different contact mechanics and
    artifact profiles.
  eeg_electrode_system (TEXT): site nomenclature/layout system — e.g. 10-20,
    10-10, or a custom device layout.
  eeg_electrode_type (TEXT): wet, dry, sponge, or other. EEG measures scalp
    voltage differences in microvolts, so impedance/contact mechanics matter.
  sampling_frequency (FLOAT): Hz rate for all EEG channels. MNE's
    create_info() requires it as its first argument.
  eeg_channel_count (INTEGER): total channels declared in this recording.
    Used by the MNE pipeline to validate that eeg_samples row count
    matches the declared layout.
  eeg_channel_names (JSONB array): canonical per-channel labels from the
    device or acquisition config. Used by the forwarder to name channel_id
    values when real hardware provides channel-specific names.
  cap_manufacturer (TEXT): e.g., 'Brain Products', 'OpenBCI'. Required
    for the batch layer to select the correct electrode coordinate file.
  cap_manufacturer_model_name (TEXT): e.g., 'actiCAP snap', 'Ultracortex
    Mark IV'. Different models have different electrode layouts.
  eeg_electrode_type (TEXT): ag_agcl (wet/gel) vs dry. Wet Ag/AgCl
    electrodes have a ~100x lower noise floor. The SQI monitor applies
    different impedance thresholds depending on electrode type.
  eeg_skin_prep (TEXT): scalp preparation before cap electrode placement.
    Abrasion and cleaning reduce contact impedance significantly. Two
    sessions with identical caps but different skin prep produce
    non-comparable signal quality baselines.

WHY HRV METADATA FIELDS:
  hrv_signal_source (TEXT): the physical signal from which R-R intervals
    were extracted — 'ecg' (gold standard), 'pcg' (acoustic), or 'ppg'
    (optical). PPG intervals cannot be directly compared to ECG intervals
    without correcting for pulse transit time. The batch layer branches
    on this value.
  hrv_electrode_placement / hrv_electrode_type (TEXT): where and how the HRV
    source was sensed. ECG uses electrical electrodes and stores R-R intervals
    derived from cardiac voltage; PPG/PCG may use optical or acoustic sensors
    and can mark electrode fields as not_applicable.
  beat_detection_algorithm / beat_detection_version (TEXT): reproducible
    HRV features need a known extraction algorithm and version. This is
    the HRV equivalent of the algorithm_name / algorithm_version columns
    on alert_events.

WHY EDA METADATA FIELDS:
  eda_electrode_placement (TEXT): palmar / thenar / plantar / other.
    Different placements produce different baseline conductance values.
    cvxEDA normalization requires placement to apply correct reference
    ranges.
  eda_electrode_type (TEXT): ag_agcl vs dry. Wet Ag/AgCl electrodes have
    a 100x lower noise floor. The SQI monitor applies different
    thresholds depending on electrode type.
  eda_skin_prep (TEXT): abrading or cleaning skin before electrode placement
    changes impedance dramatically. Two sessions with identical
    electrodes but different skin prep produce non-comparable baselines.
  eda_signal_source (TEXT): 'combined' (raw, batch layer runs cvxEDA)
    vs 'scl' / 'scr' (device has already decomposed; batch layer skips
    cvxEDA).
  eda_range_min_us / eda_range_max_us (FLOAT): declared hardware
    measurement range. The SQI monitor flags samples near the limit as
    potentially saturating.

WHY RESPIRATION METADATA FIELDS:
  respiration_source (TEXT): 'belt_direct' or 'rsa_derived'. Belt data
    is ground truth; RSA-derived is computed from R-R intervals. Error
    characteristics differ completely. The batch layer must know which
    source produced the session's samples.
  is_derived (BOOLEAN): convenience flag — true = any computed/inferred
    signal, false = direct hardware measurement. Lets the safety monitor
    filter by derivation type with a simple WHERE clause without string
    matching on respiration_source.
  respiration_unit (TEXT): the physical unit of the raw_amplitude values
    in respiration_samples — e.g., 'mV', 'percentage', 'ohm', 'arbitrary'.
    Constant across all samples in the session; moved here from the
    per-sample table.

WHY updated_at TRIGGER:
  Same rationale as sessions (migration 002). Metadata corrections
  (e.g., wrong cap model entered at session start) must be traceable
  via updated_at without application code forgetting to set it.

NOTE ON INDEXES:
  Indexes for this table (idx_session_signal_metadata_tenancy and
  idx_session_signal_metadata_session) are defined in migration 023,
  where all indexes across the schema are consolidated.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "019_session_signal_metadata"
down_revision: Union[str, None] = "015_schema_version_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE session_signal_metadata (
            id                          UUID        NOT NULL DEFAULT gen_random_uuid(),
            session_id                  UUID        NOT NULL,
            site_id                     UUID        NOT NULL,
            sponsor_id                  UUID        NOT NULL,
            participant_id              UUID        NOT NULL,
            device_id                   UUID        NOT NULL,
            capture_source              TEXT        NOT NULL DEFAULT 'simulated'
                                        CHECK (capture_source IN (
                                            'simulated', 'hardware'
                                        )),
            modality                    TEXT        NOT NULL
                                        CHECK (modality IN (
                                            'eeg', 'hrv', 'eda', 'respiration'
                                        )),

            -- Shared across applicable modalities
            software_filters            JSONB
                                        CHECK (
                                            software_filters IS NULL OR
                                            jsonb_typeof(software_filters) = 'object' OR
                                            software_filters = '"n/a"'::jsonb
                                        ),
            power_line_frequency        FLOAT,
            sample_rate_hz              FLOAT,

            -- EEG-specific recording metadata
            eeg_reference               TEXT,
            eeg_sensor_form             TEXT
                                        CHECK (eeg_sensor_form IS NULL OR
                                               eeg_sensor_form IN (
                                                   'cap', 'individual_electrodes',
                                                   'dry_headset', 'other', 'unknown'
                                               )),
            eeg_electrode_system        TEXT
                                        CHECK (eeg_electrode_system IS NULL OR
                                               eeg_electrode_system IN (
                                                   'ten_twenty', 'ten_ten',
                                                   'custom', 'unknown'
                                               )),
            eeg_electrode_type          TEXT
                                        CHECK (eeg_electrode_type IS NULL OR
                                               eeg_electrode_type IN (
                                                   'wet', 'dry', 'sponge',
                                                   'other', 'unknown'
                                               )),
            sampling_frequency          FLOAT,
            eeg_channel_count           INTEGER
                                        CHECK (eeg_channel_count IS NULL OR eeg_channel_count >= 0),
            eeg_channel_names           JSONB
                                        CHECK (
                                            eeg_channel_names IS NULL OR
                                            jsonb_typeof(eeg_channel_names) = 'array'
                                        ),
            cap_manufacturer            TEXT,
            cap_manufacturer_model_name TEXT,
            eeg_electrode_type          TEXT
                                        CHECK (eeg_electrode_type IS NULL OR
                                               eeg_electrode_type IN (
                                                   'ag_agcl', 'dry', 'other'
                                               )),
            eeg_skin_prep               TEXT
                                        CHECK (eeg_skin_prep IS NULL OR
                                               eeg_skin_prep IN (
                                                   'cleaned', 'abraded',
                                                   'cleaned_and_abraded',
                                                   'none', 'unknown'
                                               )),

            -- HRV-specific recording metadata
            hrv_signal_source           TEXT
                                        CHECK (hrv_signal_source IS NULL OR
                                               hrv_signal_source IN ('ecg', 'pcg', 'ppg')),
            hrv_electrode_placement     TEXT
                                        CHECK (hrv_electrode_placement IS NULL OR
                                               hrv_electrode_placement IN (
                                                   'chest', 'limb_leads', 'wrist',
                                                   'finger', 'ear', 'other',
                                                   'not_applicable', 'unknown'
                                               )),
            hrv_electrode_type          TEXT
                                        CHECK (hrv_electrode_type IS NULL OR
                                               hrv_electrode_type IN (
                                                   'ag_agcl', 'dry', 'textile',
                                                   'optical', 'piezo', 'other',
                                                   'not_applicable', 'unknown'
                                               )),
            beat_detection_algorithm    TEXT,
            beat_detection_version      TEXT,

            -- EDA-specific recording metadata
            eda_electrode_placement     TEXT
                                        CHECK (eda_electrode_placement IS NULL OR
                                               eda_electrode_placement IN (
                                                   'palmar', 'thenar', 'plantar', 'other'
                                               )),
            eda_electrode_type          TEXT
                                        CHECK (eda_electrode_type IS NULL OR
                                               eda_electrode_type IN (
                                                   'ag_agcl', 'dry', 'other'
                                               )),
            eda_skin_prep               TEXT
                                        CHECK (eda_skin_prep IS NULL OR
                                               eda_skin_prep IN (
                                                   'cleaned', 'abraded',
                                                   'cleaned_and_abraded',
                                                   'none', 'unknown'
                                               )),
            eda_signal_source           TEXT
                                        CHECK (eda_signal_source IS NULL OR
                                               eda_signal_source IN (
                                                   'combined', 'scl', 'scr'
                                               )),
            eda_range_min_us            FLOAT,
            eda_range_max_us            FLOAT,

            -- Respiration-specific recording metadata
            respiration_source          TEXT
                                        CHECK (respiration_source IS NULL OR
                                               respiration_source IN (
                                                   'belt_direct', 'rsa_derived'
                                               )),
            is_derived                  BOOLEAN,
            respiration_unit            TEXT,

            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            PRIMARY KEY (session_id, modality)
        );

        CREATE TRIGGER session_signal_metadata_set_updated_at
        BEFORE UPDATE ON session_signal_metadata
        FOR EACH ROW
        EXECUTE FUNCTION set_updated_at();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TRIGGER IF EXISTS session_signal_metadata_set_updated_at
        ON session_signal_metadata;
        DROP TABLE IF EXISTS session_signal_metadata;
    """)
