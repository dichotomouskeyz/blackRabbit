# AGENTS.md - Codex Context

This file is the canonical AI-agent operating contract for this repository.
Tool-specific files in `.codex/` and `.claude/` should mirror this context, not
replace it.

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
- use parameterized SQL for values
- keep literal table names in dynamic SQL from closed internal mappings
- preserve separate EEG, HRV, EDA, and respiration tables
- preserve structured JSON logging
- preserve pseudonymous IDs
- preserve raw APEX/ECHO records
- preserve replayability
- preserve ECHO/APEX/ARC terminology
- add focused tests when behavior changes

## Coding Rules

- Use Python 3.12+ and `uv`.
- Keep module changes scoped to the subsystem being changed.
- Prefer explicit dataclasses and small functions over broad service objects.
- Use Ruff for linting and formatting checks.
- Do not commit `.env`, logs, data artifacts, caches, or XDF files.
- Unit tests should avoid a DB unless behavior requires one.
- DB-backed tests use `@pytest.mark.integration` and `TEST_DATABASE_URL`.

## Working Style

Read the relevant module and tests before editing. Prefer small, direct changes
over broad refactors. Keep deferred systems deferred unless the user explicitly
reintroduces them: live safety/SQI semantics, broad FastAPI service, React UI,
BLE/UWB hardware, cloud infrastructure, Kafka/Flink, and heavyweight external
signal-processing stacks.
