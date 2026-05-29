# AGENTS.md - Codex Context

This file is the Codex-facing operating contract for this repository. It mirrors
the current MVP frame in `.claude/CLAUDE.md` and points phase work to the
specialized playbooks in `.codex/agents/`.

## Product Frame

Untitled Biometric Platform 1a is a local research-tool MVP for synchronized
physiological capture and post-session convergence analysis. It is not a therapy
app, wellness product, clinical trial management system, or regulated medical
device.

## Current Architecture

- APEX captures EEG, HRV, EDA, and respiration through LSL.
- ECHO captures manual contextual marker events through LSL.
- ARC means Agentic Response Convergence and runs after capture.
- Capture writes XDF first, then DB rows.
- Alembic migrations are the schema source of truth.

## Phase Agents

Use the matching phase playbook when a task belongs mainly to one remaining MVP
phase:

- Phase 3b baseline-in-batch: `.codex/agents/phase-3b-baseline.md`
- Phase 5b ARC batch: `.codex/agents/phase-5b-arc-batch.md`
- Phase 4b operator surface: `.codex/agents/phase-4b-operator-surface.md`

If a task spans phases, preserve the data order: capture first, baseline second,
ARC batch third, operator review/export last.

## Non-Negotiables

Never:
- write directly to `audit_events`
- collapse `lsl_timestamp` and `db_insert_time`
- expose real participant identity
- trigger batch work before `watermark_verified`
- bypass sponsor/site tenancy checks
- remove XDF reconciliation

Always:
- use `config/settings.py` for runtime configuration
- use Alembic for schema changes
- preserve pseudonymous IDs
- preserve raw APEX/ECHO records
- add focused tests when behavior changes

## Working Style

Read the relevant module and tests before editing. Prefer small, direct changes
over broad refactors. Keep deferred systems deferred unless the user explicitly
reintroduces them: live safety/SQI semantics, broad FastAPI service, React UI,
BLE/UWB hardware, cloud infrastructure, Kafka/Flink, and heavyweight external
signal-processing stacks.
