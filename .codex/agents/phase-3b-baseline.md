# Phase 3b Baseline Playbook

Use this playbook for baseline-in-batch tasks.

## Goal

Compute and persist reproducible baseline values after capture has completed.
This is batch work, not live monitoring.

## Build Rules

- Read complete post-session APEX records.
- Write baseline artifacts to `session_baselines`.
- Preserve raw biosignal rows unchanged.
- Determine active signals from session metadata plus samples in the relevant
  window.
- Keep config in `config/settings.py` or TOML loader modules.
- Use Alembic for schema changes.

## Do Not Build

- live safety monitor semantics
- live SQI monitor semantics
- participant intervention thresholds
- broad API/UI surfaces

## Verification

Run focused tests for deterministic baseline values, missing modality handling,
DB persistence shape, and no direct writes to `audit_events`.

## Gate Criteria

Salvaged from the retired Notion "testing strategy phase x phase" page and
translated to current naming. These are what Phase 3b must prove before Phase 5b.
Components not yet built are marked (TODO).

- `session_baselines` has one row per signal component (`hrv_rmssd`, `eda_mean`,
  `eeg_alpha_power`, …) after a simulated session.
- Signal-component extraction is deterministic for known input, and baseline
  computation and ARC use the *same* extraction code (no inline reimplementation
  that can diverge). (Shared `batch/arc` signal-features module — TODO.)
- Baseline window determination works for the chosen mode (first-N-minutes
  config and/or `baseline_start`/`baseline_end` ECHO markers).
- (TODO) Batch SQI gate runs against stored data and writes `sqi_flag` on flagged
  samples; `sqi_flag` exists on all four biosignal hypertables.
- (TODO) Batch safety scan runs against stored data, skips `sqi_flag = true`
  samples, fires an `alert_events` row on an injected cardiac anomaly, and writes
  `algorithm_name`/`algorithm_version`/`algorithm_parameters` on every alert.
- Integration: the batch chain runs in order baseline → SQI → safety, each step
  reading the previous step's output for the same session.
- DB-backed gates use `@pytest.mark.integration` + `TEST_DATABASE_URL`.
