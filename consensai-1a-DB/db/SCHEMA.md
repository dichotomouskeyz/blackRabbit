# Consensai 1a — Database Schema

Generated from migrations 001–025. All IDs are UUIDs unless noted.

---

## Extensions (001)

| Extension | Purpose |
|-----------|---------|
| `timescaledb` | Hypertable partitioning for high-volume biosignal tables |
| `pgvector` | Vector storage for future embedding columns (planted, not populated in 1a) |
| `uuid-ossp` | UUID generation functions |

---

## Core Session Table (002)

### `sessions`
Primary clinical record. One row per recording session.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` PK | `gen_random_uuid()` |
| `site_id` | `UUID NOT NULL` | Site conducting the session |
| `sponsor_id` | `UUID NOT NULL` | Trial sponsor |
| `participant_id` | `UUID NOT NULL` | Pseudonymous — real identity never stored |
| `room_id` | `UUID` | Physical room within the site |
| `protocol_arm` | `TEXT` | e.g. `'high_dose_25mg'`, `'placebo'` |
| `compound` | `TEXT NOT NULL` | Must match `compound_reference.compound_id` |
| `compound_dose` | `DOUBLE PRECISION` | Numeric dose value |
| `compound_dose_unit` | `TEXT` | `mg` \| `ug` \| `µg` \| `mg/kg` \| `ug/kg` \| `µg/kg` |
| `therapist_id` | `TEXT` | Therapist identifier |
| `status` | `session_status` NOT NULL | ENUM: `initializing → active → closing → closed / failed` |
| `batch_processed_at` | `TIMESTAMPTZ` | NULL = batch not yet run |
| `started_at` | `TIMESTAMPTZ` | |
| `closed_at` | `TIMESTAMPTZ` | Set on `closed` or `failed` |
| `created_at` | `TIMESTAMPTZ NOT NULL` | `DEFAULT NOW()` |
| `updated_at` | `TIMESTAMPTZ NOT NULL` | Auto-updated by `set_updated_at()` trigger |

**Triggers:** `sessions_set_updated_at` (BEFORE UPDATE), `sessions_watermark_trigger` (AFTER UPDATE — fires on `closed`/`failed` → writes to `audit_events`)

**Indexes (023):** `sponsor_id`, `site_id`, `protocol_arm`, `(sponsor_id, site_id)`, `status`, `compound`

---

## Reference Data (003)

### `compound_reference`
Closed vocabulary of DEA Schedule I compounds used in trials.

| Column | Type | Notes |
|--------|------|-------|
| `compound_id` | `TEXT` PK | e.g. `'psilocybin'`, `'mdma'`, `'ibogaine_hcl'` |
| `display_name` | `TEXT NOT NULL` | Human-readable label |
| `iupac_name` | `TEXT NOT NULL` | Authoritative chemical name |
| `cas_number` | `TEXT NOT NULL UNIQUE` | DEA/FDA registry identifier |
| `notes` | `TEXT` | |

**Seed data:** lsd, psilocybin, psilocin, dmt, 5meo_dmt, ibogaine, ibogaine_hcl, mdma

---

## Biosignal Hypertables (004–007)

All four tables share this tenancy/identity header. Partitioned by `db_insert_time` (1-hour chunks).

**Common columns on all biosignal tables:**

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID NOT NULL` | `gen_random_uuid()` — surrogate reference key |
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `device_id` | `UUID NOT NULL` | |
| `lsl_timestamp` | `DOUBLE PRECISION NOT NULL` | Device capture time (LSL clock) |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | Wall clock at write — always ≠ lsl_timestamp |
| `sqi_flag` | `SMALLINT` | Written by sqi_monitor.py; NULL until evaluated |
| `sample_index` | `BIGINT NOT NULL` | Monotonic sample counter per session |

### `eeg_samples`
Narrow-row format: one row per channel per sample.

| Column | Type | Notes |
|--------|------|-------|
| `channel_id` | `TEXT NOT NULL` | e.g. `'ch_0'` |
| `voltage` | `FLOAT NOT NULL` | Microvolts |
| **PK** | `(session_id, lsl_timestamp, channel_id, db_insert_time)` | |

**Indexes:** `(session_id, lsl_timestamp DESC)`, `(site_id, sponsor_id)`, `(session_id, channel_id, lsl_timestamp DESC)`

### `hrv_samples`

| Column | Type | Notes |
|--------|------|-------|
| `rr_interval_ms` | `FLOAT NOT NULL` | Primary R-R interval |
| `heart_rate_bpm` | `FLOAT` | Derived; nullable |
| `beat_quality` | `SMALLINT` | |
| **PK** | `(id, session_id, lsl_timestamp, db_insert_time)` | |

### `eda_samples`
Electrodermal activity (galvanic skin response).

| Column | Type | Notes |
|--------|------|-------|
| `raw_conductance_us` | `FLOAT NOT NULL` | Direct hardware output — never filtered |
| `conductance_us` | `FLOAT NOT NULL` | After software_filters |
| `signal_quality` | `FLOAT` | |
| **PK** | `(id, session_id, lsl_timestamp, db_insert_time)` | |

### `respiration_samples`

| Column | Type | Notes |
|--------|------|-------|
| `raw_amplitude` | `FLOAT NOT NULL` | Direct hardware output |
| `processed_amplitude` | `FLOAT NOT NULL` | After software_filters |
| `breath_phase` | `TEXT` | `inhale` \| `exhale` \| `hold` |
| `breaths_per_min` | `FLOAT` | Derived by capture layer |
| **PK** | `(id, session_id, lsl_timestamp, db_insert_time)` | |

---

## Audit & Event Tables (008–010)

### `audit_events`
**Append-only.** Written exclusively by database triggers — never by application code.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID` | Nullable (system events may have no session) |
| `event_type` | `TEXT NOT NULL` | e.g. `INSERT`, `watermark_verified`, `watermark_failed` |
| `table_name` | `TEXT` | Source table |
| `record_id` | `TEXT` | Source row ID |
| `actor_id` | `TEXT` | |
| `payload` | `JSONB NOT NULL` | Full row or identifying fields depending on trigger tier |
| `event_timestamp` | `TIMESTAMPTZ NOT NULL` | When the event occurred |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | When this audit row was written |

**Permissions:** `REVOKE UPDATE, DELETE FROM PUBLIC`

**Indexes:** `(session_id, event_timestamp DESC)`

### `alert_events`
Automated safety/quality alerts from `safety_monitor.py`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `alert_type` | `TEXT NOT NULL` | `cardiac` \| `sqi` \| `respiration` \| `device_loss` \| `threshold_breach` \| `process_restart` |
| `compound` | `TEXT NOT NULL` | |
| `compound_dose` | `FLOAT NOT NULL` | |
| `severity` | `TEXT NOT NULL` | `info` \| `warning` \| `critical` |
| `stream_type` | `TEXT` | |
| `channel_name` | `TEXT` | |
| `trigger_value` | `DOUBLE PRECISION` | |
| `threshold_value` | `DOUBLE PRECISION` | |
| `algorithm_name` | `TEXT NOT NULL` | **Regulatory: FDA Hurdle 5** |
| `algorithm_version` | `TEXT NOT NULL` | |
| `algorithm_parameters` | `JSONB NOT NULL` | Parameters at alert time |
| `message` | `TEXT` | |
| `acknowledged_by` | `TEXT` | |
| `acknowledged_at` | `TIMESTAMPTZ` | Pair constraint: both NULL or both non-NULL |
| `lsl_timestamp` | `DOUBLE PRECISION` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |
| `embedding` | `vector(384)` | Planted; NULL in 1a |

**Indexes:** `(session_id, severity)`, `(session_id) WHERE acknowledged_at IS NULL`

### `humen_events`
HUMeN proximity state events from LSL Marker Stream (manual in 1a).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `event_type` | `TEXT NOT NULL` | e.g. `proximity_state_change` |
| `source` | `TEXT NOT NULL` | `manual_logging` \| `imu_derived` |
| `actor_id` | `TEXT NOT NULL` | Person being logged |
| `actor_role` | `TEXT` | `therapist` \| `facilitator` \| `coordinator` \| `observer` |
| `zone_id` | `TEXT` | |
| `zone_label` | `TEXT NOT NULL` | `arms_reach` \| `in_room` \| `leaving_room` \| `out_of_room` |
| `sample_index` | `BIGINT` | |
| `confidence_score` | `FLOAT` | 0.0–1.0; NULL in 1a manual mode |
| `metadata` | `JSONB` | |
| `lsl_timestamp` | `DOUBLE PRECISION NOT NULL` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |

**Indexes:** `(session_id, lsl_timestamp)`, `actor_id`, `zone_label`

---

## Vector / Feature Tables (011)

### `session_feature_vectors`
Batch-computed features (MNE/Neurokit2). Populated post-session.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `feature_type` | `TEXT NOT NULL` | |
| `feature_version` | `TEXT NOT NULL` | |
| `feature_values` | `JSONB NOT NULL` | |
| `embedding` | `vector(384)` | Planted; NULL in 1a |
| `computed_at` | `TIMESTAMPTZ NOT NULL` | |

### `session_notes`
Coordinator observations with future embedding support.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `author_id` | `TEXT NOT NULL` | |
| `note_type` | `TEXT NOT NULL` | Default `'observation'` |
| `content` | `TEXT NOT NULL` | |
| `embedding` | `vector(384)` | Planted; NULL in 1a |
| `lsl_timestamp` | `DOUBLE PRECISION` | Nullable: live notes have LSL ts; post-hoc notes do not |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |

---

## Regulatory Tables (014–018)

### `participant_consent_log`
21 CFR Part 11 — one row per consent event, independent of sessions.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `participant_id` | `UUID NOT NULL` | |
| `session_id` | `UUID` | Nullable — consent can precede session creation |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `protocol_id` | `TEXT NOT NULL` | |
| `consent_version` | `TEXT NOT NULL` | IRB form version |
| `consent_type` | `TEXT NOT NULL` | `initial` \| `updated` \| `reconsent` |
| `consented_at` | `TIMESTAMPTZ NOT NULL` | |
| `consent_obtained_by` | `TEXT NOT NULL` | |
| `consent_method` | `TEXT NOT NULL` | `electronic_signature` \| `in_person` \| `video` \| `other` |
| `revoked_at` | `TIMESTAMPTZ` | |
| `revocation_reason` | `TEXT` | |
| `notes` | `TEXT` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |

### `schema_version_log`
Computational provenance — one row per session start.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `alembic_version` | `TEXT NOT NULL` | Migration head at session start |
| `app_version` | `TEXT NOT NULL` | Semver from `APP_VERSION` env var |
| `python_version` | `TEXT` | |
| `postgres_version` | `TEXT` | |
| `timescaledb_version` | `TEXT` | |
| `pgvector_version` | `TEXT` | |
| `mne_version` | `TEXT` | |
| `neurokit2_version` | `TEXT` | |
| `pylsl_version` | `TEXT` | |
| `recorded_at` | `TIMESTAMPTZ NOT NULL` | |

### `electronic_signatures`
**Append-only.** 21 CFR Part 11 Section 11.50 legal signature record.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID` | Nullable |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `signer_id` | `TEXT NOT NULL` | |
| `signer_printed_name` | `TEXT NOT NULL` | Required by Part 11 |
| `signer_role` | `TEXT NOT NULL` | |
| `signature_meaning` | `TEXT NOT NULL` | `session_opened` \| `session_closed` \| `dose_administered` \| `adverse_event_reviewed` \| `adverse_event_reported` \| `alert_acknowledged` \| `consent_obtained` \| `protocol_deviation_logged` \| `data_export_authorized` \| `audit_review_completed` |
| `table_name` | `TEXT NOT NULL` | Signed record's table |
| `record_id` | `TEXT NOT NULL` | Signed record's row ID |
| `signature_hash` | `TEXT NOT NULL` | SHA-256 of signed record at signing time |
| `signed_at` | `TIMESTAMPTZ NOT NULL` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |

**Permissions:** `REVOKE UPDATE, DELETE FROM PUBLIC`

### `investigational_product_log`
**Append-only.** DEA Schedule I substance chain of custody.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID` | Nullable (receipt/storage events have no session) |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `compound` | `TEXT NOT NULL` | |
| `lot_number` | `TEXT NOT NULL` | DEA accountability unit |
| `coa_reference` | `TEXT` | Certificate of Analysis reference |
| `event_type` | `TEXT NOT NULL` | `receipt` \| `storage_check` \| `preparation` \| `transfer` \| `administration` \| `return` \| `destruction` \| `reconciliation` |
| `quantity_mg` | `DOUBLE PRECISION` | |
| `quantity_unit` | `TEXT` | |
| `quantity_remaining_mg` | `DOUBLE PRECISION` | |
| `performed_by` | `TEXT NOT NULL` | |
| `witnessed_by` | `TEXT` | Required by DEA for preparation/destruction |
| `storage_location` | `TEXT` | |
| `temperature_c` | `DOUBLE PRECISION` | |
| `notes` | `TEXT` | |
| `event_timestamp` | `TIMESTAMPTZ NOT NULL` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |

**Permissions:** `REVOKE UPDATE, DELETE FROM PUBLIC`

### `adverse_event_log`
Formal clinical AE designations (distinct from automated `alert_events`).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `compound` | `TEXT NOT NULL` | |
| `ae_term` | `TEXT NOT NULL` | |
| `ae_description` | `TEXT NOT NULL` | |
| `ctcae_grade` | `SMALLINT NOT NULL` | 1–5 (FDA standard CTCAE scale) |
| `is_serious` | `BOOLEAN NOT NULL` | Grade 3+ triggers expedited reporting |
| `relatedness` | `TEXT NOT NULL` | `unrelated` \| `unlikely` \| `possible` \| `probable` \| `definite` |
| `onset_timestamp` | `TIMESTAMPTZ NOT NULL` | |
| `resolution_timestamp` | `TIMESTAMPTZ` | |
| `outcome` | `TEXT` | `resolved` \| `resolving` \| `not_resolved` \| `resolved_with_sequelae` \| `medical_intervention` \| `hospitalization` \| `fatal` \| `other` \| `unknown` |
| `action_taken` | `TEXT` | `none` \| `dose_not_changed` \| `dose_reduced` \| `dose_held` \| `drug_discontinued` \| `emergency_services_called` \| `medication_given` \| `other` |
| `reported_by` | `TEXT NOT NULL` | |
| `reviewed_by` | `TEXT` | |
| `irb_reported_at` | `TIMESTAMPTZ` | |
| `fda_reported_at` | `TIMESTAMPTZ` | NULL = not yet reported |
| `linked_alert_id` | `BIGINT` | Links to `alert_events.id` |
| `notes` | `TEXT` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL` | Auto-updated by trigger |

**Triggers:** `adverse_event_log_set_updated_at`

---

## Recording Metadata (019)

### `session_signal_metadata`
One row per `(session_id, modality)` — static recording setup, not per-sample data.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID NOT NULL` | `gen_random_uuid()` |
| `session_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | |
| `device_id` | `UUID NOT NULL` | |
| `modality` | `TEXT NOT NULL` | `eeg` \| `hrv` \| `eda` \| `respiration` |
| `software_filters` | `JSONB` | Object-of-objects or `"n/a"` |
| `power_line_frequency` | `FLOAT` | For notch filter (EEG, HRV) |
| `sample_rate_hz` | `FLOAT` | EDA, respiration |
| `eeg_reference` | `TEXT` | e.g. `'average'`, `'Cz'` |
| `sampling_frequency` | `FLOAT` | EEG Hz |
| `eeg_channel_count` | `INTEGER` | |
| `cap_manufacturer` | `TEXT` | |
| `cap_manufacturer_model_name` | `TEXT` | |
| `hrv_signal_source` | `TEXT` | `ecg` \| `pcg` \| `ppg` |
| `beat_detection_algorithm` | `TEXT` | |
| `beat_detection_version` | `TEXT` | |
| `electrode_placement` | `TEXT` | `palmar` \| `thenar` \| `plantar` \| `other` |
| `electrode_type` | `TEXT` | `ag_agcl` \| `dry` \| `other` |
| `skin_prep` | `TEXT` | `cleaned` \| `abraded` \| `cleaned_and_abraded` \| `none` \| `unknown` |
| `eda_signal_source` | `TEXT` | `combined` \| `scl` \| `scr` |
| `eda_range_min_us` | `FLOAT` | |
| `eda_range_max_us` | `FLOAT` | |
| `respiration_source` | `TEXT` | `belt_direct` \| `rsa_derived` |
| `is_derived` | `BOOLEAN` | `true` = inferred signal |
| `respiration_unit` | `TEXT` | e.g. `'mV'`, `'percentage'` |
| `created_at` | `TIMESTAMPTZ NOT NULL` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL` | Auto-updated by trigger |
| **PK** | `(session_id, modality)` | |

---

## Audit Triggers (020)

Two trigger functions cover all tables:

| Function | Tables | Payload |
|----------|--------|---------|
| `audit_trigger_full_func()` | sessions, alert_events, humen_events, session_feature_vectors, session_notes, participant_consent_log, schema_version_log, electronic_signatures, investigational_product_log, adverse_event_log, session_signal_metadata, data_correction_amendment_log, session_environment_log | Full row as JSONB |
| `audit_trigger_lightweight_func()` | eeg_samples, hrv_samples, eda_samples, respiration_samples | `{sample_index, lsl_timestamp, device_id}` only |

---

## Correction & Environment Logs (021–022)

### `data_correction_amendment_log`
21 CFR Part 11 Section 11.10(e) — structured correction record with approval chain.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `table_name` | `TEXT NOT NULL` | Corrected table |
| `record_id` | `TEXT NOT NULL` | Corrected row |
| `column_name` | `TEXT NOT NULL` | |
| `original_value` | `TEXT` | Must be preserved |
| `corrected_value` | `TEXT NOT NULL` | |
| `correction_reason` | `TEXT NOT NULL` | |
| `correction_type` | `TEXT NOT NULL` | `transcription_error` \| `protocol_clarification` \| `missing_data` \| `unit_error` \| `device_calibration` \| `other` |
| `requested_by` | `TEXT NOT NULL` | |
| `approved_by` | `TEXT` | NULL = pending approval |
| `approved_at` | `TIMESTAMPTZ` | |
| `query_reference` | `TEXT` | DCF reference (FK to data_query_log deferred to 1b) |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL` | Auto-updated by trigger |

**Permissions:** `REVOKE DELETE FROM PUBLIC` (UPDATE allowed for approval workflow)

### `session_environment_log`
**Append-only.** Time-series environmental observations.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `temperature_c` | `FLOAT` | |
| `humidity_percent` | `FLOAT` | 0–100 |
| `light_level` | `TEXT` | `dim` \| `low` \| `moderate` \| `bright` \| `other` |
| `noise_level` | `TEXT` | `silent` \| `quiet` \| `moderate` \| `loud` \| `other` |
| `music_playing` | `BOOLEAN NOT NULL` | Default `FALSE` |
| `disruptions` | `TEXT` | |
| `recorded_by` | `TEXT NOT NULL` | |
| `lsl_timestamp` | `DOUBLE PRECISION` | Nullable — NULL for post-hoc entries |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |

**Permissions:** `REVOKE UPDATE, DELETE FROM PUBLIC`

---

## Watermark Trigger (024)

`sessions_watermark_trigger` fires AFTER UPDATE on `sessions`:

| Status transition | Audit event written |
|-------------------|---------------------|
| any → `closed` | `watermark_verified` — gates post-session batch processing |
| any → `failed` | `watermark_failed` — blocks batch, alerts coordinator |

---

## Clock Drift Log (025)

### `clock_drift_log`
Durably records LSL-to-NTP clock offset at regular intervals. Non-optional for ibogaine 8-hour sessions.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `device_id` | `UUID NOT NULL` | |
| `stream_type` | `TEXT NOT NULL` | `EEG` \| `HRV` \| `EDA` \| `Respiration` |
| `remote_clock_offset_s` | `DOUBLE PRECISION NOT NULL` | `inlet.time_correction()` value |
| `exceeds_threshold` | `BOOLEAN NOT NULL` | `abs(offset) > DRIFT_WARN_THRESHOLD_S` |
| `threshold_s` | `DOUBLE PRECISION NOT NULL` | Threshold value at measurement time |
| `lsl_timestamp` | `DOUBLE PRECISION NOT NULL` | When offset was sampled (LSL clock) |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | When row was committed |

**Indexes:** `(session_id, stream_type, db_insert_time DESC)`, `(sponsor_id, site_id, db_insert_time DESC)`

---

## Regulatory Invariants

| Rule | Enforcement |
|------|-------------|
| Audit trail via triggers only — never application code | `REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC` + trigger-only writes |
| `lsl_timestamp` ≠ `db_insert_time` — always separate columns | Schema design; two-timestamp rule on every table |
| Algorithm governance on every alert | `algorithm_name`, `algorithm_version`, `algorithm_parameters` NOT NULL on `alert_events` |
| Pseudonymous IDs only — real identity never stored | `participant_id` is a site-generated token |
| Data tenancy on every table | `site_id UUID NOT NULL` + `sponsor_id UUID NOT NULL` everywhere |
| Batch only after `watermark_verified` | `sessions_watermark_trigger` gates batch pipeline |
| XDF backup always written in parallel | `xdf_writer.py` runs alongside TimescaleDB writes |
| Clock drift always recorded | `clock_drift_log` populated by `lsl_forwarder.py` every `CLOCK_DRIFT_RECORD_INTERVAL` seconds |
