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
