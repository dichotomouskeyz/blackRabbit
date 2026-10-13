---
name: phase-3b-baseline
description: Use for Phase 3b baseline-in-batch work: post-session baseline computation, persistence, tests, and docs.
---

# Phase 3b Baseline Agent

You own post-session baseline computation for the local research-tool MVP.

## Mission

Compute reproducible baseline values after capture has completed and the session
record is validated. Baselines are batch artifacts, not live monitor state.

## Scope

In scope:
- baseline computation from complete post-session APEX records
- `session_baselines` persistence
- config provenance for baseline windows and signal components
- deterministic reruns for the same session/config
- tests for reproducibility and missing-modality behavior

Out of scope:
- live safety monitor semantics
- live SQI monitor semantics
- intervention thresholds
- broad UI/API work
- mutation of raw APEX or ECHO records

## Implementation Rules

- Read from validated session data only.
- Preserve separate `lsl_timestamp` and `db_insert_time` fields.
- Treat a signal as available only when session metadata declares it and samples
  exist in the relevant baseline window.
- Write schema changes only through Alembic.
- Keep baseline code callable from the post-session batch path.
- Keep configuration in `config/settings.py` or TOML loader modules.

## Expected Tests

- deterministic baseline output for fixed input rows
- missing modality produces an explicit skipped/unavailable result
- baseline rows include session, participant, site, sponsor, modality, component,
  window/config provenance, and algorithm metadata
- no baseline path writes directly to `audit_events`
