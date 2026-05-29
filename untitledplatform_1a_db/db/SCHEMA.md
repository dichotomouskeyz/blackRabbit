# untitledplatform_1a — Database Schema

Generated from core migrations 001–031. All IDs are UUIDs unless noted.

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
| `capture_mode` | `TEXT NOT NULL` | `simulated` \| `hardware` |
| `room_id` | `UUID` | Physical room within the site |
| `protocol_arm` | `TEXT` | e.g. `'high_dose_25mg'`, `'placebo'` |
| `compound` | `TEXT NOT NULL` | Must match `compound_reference.compound_id` |
| `compound_dose` | `DOUBLE PRECISION` | Numeric dose value |
| `compound_dose_unit` | `TEXT` | `mg` \| `ug` \| `µg` \| `mg/kg` \| `ug/kg` \| `µg/kg` |
| `therapist_id` | `TEXT` | Therapist identifier |
| `status` | `session_status` NOT NULL | ENUM: `initializing` \| `active` \| `closing` \| `closed` \| `failed` |
| `started_at` | `TIMESTAMPTZ` | |
| `closed_at` | `TIMESTAMPTZ` | Set on `closed` or `failed` |
| `created_at` | `TIMESTAMPTZ NOT NULL` | `DEFAULT NOW()` |
| `updated_at` | `TIMESTAMPTZ NOT NULL` | Auto-updated by `set_updated_at()` trigger |

**Triggers:** `sessions_set_updated_at` (BEFORE UPDATE), `sessions_watermark_trigger` (AFTER UPDATE — writes status transitions, plus terminal watermarks, to `audit_events`)

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
| `cas_number` | `TEXT NOT NULL UNIQUE` | Chemical registry identifier |
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
| `alert_type` | `TEXT NOT NULL` | `cardiac` \| `sqi` \| `respiration` \| `device_loss` \| `threshold_breach` \| `process_restart` \| `arc_failure` |
| `compound` | `TEXT NOT NULL` | |
| `compound_dose` | `FLOAT` | Nullable when dose is unknown |
| `severity` | `TEXT NOT NULL` | `info` \| `warning` \| `critical` |
| `stream_type` | `TEXT` | |
| `channel_name` | `TEXT` | |
| `trigger_value` | `DOUBLE PRECISION` | |
| `threshold_value` | `DOUBLE PRECISION` | |
| `algorithm_name` | `TEXT NOT NULL` | Reproducibility metadata |
| `algorithm_version` | `TEXT NOT NULL` | |
| `algorithm_parameters` | `JSONB NOT NULL` | Parameters at alert time |
| `message` | `TEXT` | |
| `lsl_timestamp` | `DOUBLE PRECISION` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |
| `embedding` | `vector(384)` | Planted; NULL in 1a |

**Indexes:** `(session_id, severity)`

### `echo_events`
ECHO proximity state events from LSL Marker Stream (manual in 1a).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `event_type` | `TEXT NOT NULL` | `zone_enter` \| `zone_exit` \| `manual_marker` |
| `source` | `TEXT NOT NULL` | `manual_logging` \| `imu_derived` |
| `actor_id` | `TEXT NOT NULL` | Person being logged |
| `actor_role` | `TEXT NOT NULL` | `therapist` \| `facilitator` \| `coordinator` \| `observer` |
| `zone_id` | `TEXT` | |
| `zone_label` | `TEXT NOT NULL` | proximity zone or manual marker label |
| `confidence_score` | `FLOAT` | 0.0–1.0; NULL in 1a manual mode |
| `metadata` | `JSONB` | |
| `lsl_timestamp` | `DOUBLE PRECISION NOT NULL` | |
| `db_insert_time` | `TIMESTAMPTZ NOT NULL` | |

**Indexes:** `(session_id, lsl_timestamp)`, `actor_id`, `zone_label`

---

## ARC Tables (027-028)

### `session_baselines`
Persisted baseline values for ARC. One row per signal component per session. ARC computation is deferred in the open-source 1a MVP, so no processor writes these rows yet.

| Column | Type | Notes |
|--------|------|-------|
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | Pseudonymous participant token |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `device_type` | `TEXT NOT NULL` | `simulated` \| `hardware` |
| `modality` | `TEXT NOT NULL` | `eeg` \| `hrv` \| `eda` \| `respiration` |
| `signal_component` | `TEXT NOT NULL` | e.g. `hrv_rmssd`, `eda_mean`, `eeg_alpha_power` |
| `baseline_mean` | `DOUBLE PRECISION NOT NULL` | |
| `baseline_std` | `DOUBLE PRECISION NOT NULL` | Must be >= 0 |
| `baseline_window_start` | `DOUBLE PRECISION NOT NULL` | LSL timestamp |
| `baseline_window_end` | `DOUBLE PRECISION NOT NULL` | LSL timestamp; must be after start |
| `sample_count` | `INTEGER NOT NULL` | Must be > 0 |
| `created_at` | `TIMESTAMPTZ NOT NULL` | |
| **PK** | `(session_id, modality, signal_component)` | |

**Indexes:** `session_id`, `(sponsor_id, site_id, session_id)`, `(modality, signal_component)`

### `event_composite_profiles`
Post-session ARC output table. One row per ECHO event per session that passes FDR, storing the full three-window Event Composite Profile without collapsing by interpretation mode.

ARC reads validated ECHO + APEX records after the session watermark is verified. It does not write during capture and does not replace the raw modality tables.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` PK | `gen_random_uuid()` |
| `session_id` | `UUID NOT NULL` | |
| `participant_id` | `UUID NOT NULL` | Pseudonymous participant token |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `echo_event_id` | `BIGINT NOT NULL` | FK to `echo_events.id` |
| `w1_convergence_density` | `DOUBLE PRECISION NOT NULL` | Window 1 ARC density |
| `w2_convergence_density` | `DOUBLE PRECISION NOT NULL` | Window 2 ARC density |
| `w3_convergence_density` | `DOUBLE PRECISION NOT NULL` | Window 3 ARC density |
| `w1_participating_signals` | `JSONB NOT NULL` | Array of signals participating in window 1 |
| `w2_participating_signals` | `JSONB NOT NULL` | Array of signals participating in window 2 |
| `w3_participating_signals` | `JSONB NOT NULL` | Array of signals participating in window 3 |
| `deviation_metrics` | `JSONB NOT NULL` | Per-signal, per-window deviations, including p-values/z-scores as ARC produces them |
| `null_threshold` | `DOUBLE PRECISION NOT NULL` | Threshold used against the null distribution |
| `fdr_q_value` | `DOUBLE PRECISION NOT NULL` | Event/profile q-value after FDR control |
| `passed_fdr` | `BOOLEAN NOT NULL` | True when the event/profile survives FDR control |
| `temporal_alignment_score` | `DOUBLE PRECISION` | 0.0–1.0 alignment score; nullable until computed |
| `sap_available_signals` | `JSONB NOT NULL` | Signals available for signal availability profile checks |
| `sap_participating_signals` | `JSONB NOT NULL` | Available signals that participated in the ECP |
| `arc_config_version` | `TEXT NOT NULL` | Exact ARC config version, e.g. `arc_watchdog_config.toml@...` |
| `arc_config_sha256` | `TEXT NOT NULL` | SHA-256 of the ARC config content used for the profile |
| `created_at` | `TIMESTAMPTZ NOT NULL` | |

**Constraints:** `passed_fdr IS TRUE`, unique `(session_id, echo_event_id)`

**Permissions:** `REVOKE UPDATE, DELETE FROM PUBLIC`

**Triggers:** `event_composite_profiles_audit_trigger` uses `audit_trigger_full_func()`

**Indexes:** `(session_id, created_at DESC)`, `echo_event_id`, `(sponsor_id, site_id, session_id)`, `arc_config_version`

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

## Provenance Tables (015)

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

## Optional Governance Extensions

Regulated-deployment tables for consent, electronic signatures, investigational product accountability, and adverse-event designations are no longer part of the default open-source migration chain. Their historical migrations live under `untitledplatform_1a_db/db/alembic/optional_governance/` as reference material for deployments that need them.

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
| `eeg_channel_names` | `JSONB` | Canonical channel labels, stored as an array when available |
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

## Audit Triggers (020, updated by 026–027)

Full-row audit triggers cover low-volume governance and ARC output tables. High-volume biosignal hypertables are intentionally not trigger-audited per row; `biosignal_integrity_log` records chunk-level write provenance instead.

| Function | Tables | Payload |
|----------|--------|---------|
| `audit_trigger_full_func()` | sessions, alert_events, echo_events, session_feature_vectors, session_notes, schema_version_log, session_signal_metadata, data_correction_amendment_log, session_environment_log, event_composite_profiles | Full row as JSONB |

---

## Correction & Environment Logs (021–022)

### `data_correction_amendment_log`
Structured correction record with approval fields for deployments that want a review workflow.

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

`sessions_watermark_trigger` fires AFTER UPDATE on `sessions` for genuine status changes:

| Status transition | Audit event written |
|-------------------|---------------------|
| any status change | `session_status_transition` — records old/new status |
| any → `closed` | `session_status_transition` + `watermark_verified` — gates post-session batch processing |
| any → `failed` | `session_status_transition` + `watermark_failed` — blocks batch, alerts coordinator |

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

## Biosignal Integrity Log (026)

### `biosignal_integrity_log`
One row per successfully written biosignal chunk, plus one reconciliation summary row per session close attempt. This avoids per-row audit amplification on high-volume hypertables while preserving chunk-level completeness, tamper-evidence, and the final XDF-vs-DB reconciliation record.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | |
| `session_id` | `UUID NOT NULL` | |
| `site_id` | `UUID NOT NULL` | |
| `sponsor_id` | `UUID NOT NULL` | |
| `log_type` | `TEXT NOT NULL` | `chunk_integrity` or `xdf_reconciliation` |
| `table_name` | `TEXT` | Source biosignal table; null on reconciliation rows |
| `row_count` | `INTEGER` | Rows in the written chunk; null on reconciliation rows |
| `min_sample_index` | `BIGINT` | Null on reconciliation rows |
| `max_sample_index` | `BIGINT` | Null on reconciliation rows |
| `chunk_hash` | `TEXT` | Deterministic hash of signal values in the chunk; null on reconciliation rows |
| `hash_method` | `TEXT` | Hash algorithm used to compute `chunk_hash`; null on reconciliation rows |
| `reconciliation_report` | `JSONB` | Full XDF reconciliation summary, null on chunk rows |
| `written_at` | `TIMESTAMPTZ NOT NULL` | |

**Indexes:** `(session_id, written_at)`

---

## Core Invariants

| Rule | Enforcement |
|------|-------------|
| Audit trail via triggers only — never application code | `REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC` + trigger-only writes |
| `lsl_timestamp` ≠ `db_insert_time` — always separate columns | Schema design; two-timestamp rule on every table |
| Algorithm provenance on every alert/context event | `algorithm_name`, `algorithm_version`, `algorithm_parameters` NOT NULL on `alert_events` |
| Pseudonymous IDs only — real identity never stored | `participant_id` is a site-generated token |
| Data tenancy on every table | `site_id UUID NOT NULL` + `sponsor_id UUID NOT NULL` everywhere |
| Batch only after `watermark_verified` | `sessions_watermark_trigger` gates batch pipeline |
| XDF backup always written in parallel | `xdf_writer.py` runs alongside TimescaleDB writes |
| Clock drift always recorded | `clock_drift_log` populated by `lsl_forwarder.py` every `CLOCK_DRIFT_RECORD_INTERVAL` seconds |
