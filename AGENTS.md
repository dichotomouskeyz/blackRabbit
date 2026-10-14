# AGENTS.md - blackRabbit Agent Contract

This file is the canonical AI-agent operating contract for this repository.
Tool-specific files in `.codex/` and `.claude/` mirror this context, not replace
it. If they disagree, this file wins.

> Naming: the product is **blackRabbit**. The repository directory, Python
> packages (`capture.*`, `batch.*`), and database name (`untitledplatform_1a_db`)
> still carry the legacy `untitled*` identifiers — these are intentionally not
> renamed. "Untitled Biometric Platform", "Neurobiometric", "Consensai", and
> "UCSF" are dead names; do not reintroduce them.

## Product Frame

blackRabbit 1a is a local research-tool MVP for synchronized physiological
capture and post-session convergence analysis. It is not a therapy app, wellness
product, clinical trial management system, or regulated medical device.
Regulated/clinical deployments are a deferred 1b concern, not the 1a scope.

## Current Architecture

- APEX captures EEG, HRV, EDA, and respiration through LSL.
- ECHO captures manual contextual marker events through LSL.
- ARC (Agentic Response Convergence) runs after capture: it asks which APEX
  components responded around each ECHO anchor and persists reproducible
  baseline/config provenance. It never mutates raw APEX/ECHO records.
- Capture writes XDF first, then DB rows.
- `capture/` is data acquisition. `batch/` is everything post-capture:
  `batch/arc/` (prototype preflight, processor, windows, and models; selected
  reads accept sponsor scope, but lifecycle gating and the complete ARC
  specification remain unfinished), `batch/reconciliation/`
  (XDF↔DB reconciliation + backfill), and per-modality `batch/*_batch.py`.
- Alembic migrations are the schema source of truth. Chain is clean 001→head
  `030_arc_failure_alert_type`; `untitledplatform_1a_db/db/SCHEMA.md` documents
  it. `optional_governance/` is a deliberate parallel tree for deployments that
  need it.
- DB driver is psycopg2 (a psycopg3 migration is contemplated, not started).

## Where To Look

- Release state and history: `CHANGELOG.md`, `docs/release-audit-2026-10-13.md`,
  `docs/backend-handoff.md`
- Operator UI: `web/` (agent-first Next.js console); contract in
  `.correctless/specs/frontend-shell.md`
- Historical audits of the previous implementation: `docs/2R/`
- Architecture (prose / component map): `docs/architecture.md`,
  `.correctless/ARCHITECTURE.md`
- Decisions log (authoritative): `docs/decisions.md`
- UI ↔ backend contract + deferrals: `docs/ui-integration.md`
- Feature specs (contract authority for tests): `.correctless/specs/`

## Phase Agents

Use the matching phase playbook when a task belongs mainly to one remaining MVP
phase:

- Phase 3b baseline-in-batch: `.codex/agents/phase-3b-baseline.md`
- Phase 5b ARC batch: `.codex/agents/phase-5b-arc-batch.md`
- Phase 4b operator surface: `.codex/agents/phase-4b-operator-surface.md`
- Phase 6 release hardening (checklist, no agent): `.codex/agents/phase-6-release.md`

If a task spans phases, preserve the data order: capture first, baseline second,
ARC batch third, operator review/export last.

Each phase playbook carries a Gate Criteria section — what that phase must prove
before it closes (salvaged from the retired Notion testing-strategy page).

## Workflow

- This project uses Correctless and spec-first development (adopted partway
  through the cycle, now standard). `.correctless/specs/` are the contract
  authority; tests are derived from specs.
- **Never hand-edit test files to make them pass.** A test that contradicts the
  code is reconciled against the spec: fix the implementation to the spec, or
  upgrade the spec first and regenerate the test (user-gated). If a failure can
  only be resolved by changing a test, stop and surface it.
- Record any architecturally important decision in `docs/decisions.md` using its
  house format (`## Title` / Decision / Rationale / Code impact / Date) in the
  same task it's made.

## Non-Negotiables

Never:
- write directly to `audit_events`
- collapse `lsl_timestamp` and `db_insert_time`
- expose real participant identity
- trigger batch work before `watermark_verified`
- bypass sponsor/site tenancy checks
- remove XDF reconciliation
- run raw `ALTER` against the database (schema changes go through migration files)

Always:
- use `config/settings.py` for runtime configuration
- use parameterized SQL for values
- keep literal table names in dynamic SQL from closed internal mappings
- preserve separate EEG, HRV, EDA, and respiration tables
- preserve structured JSON logging
- preserve pseudonymous IDs
- preserve raw APEX/ECHO records
- preserve replayability
- preserve ECHO/APEX/ARC terminology
- add focused tests when behavior changes (by the spec-first path above)

## Schema Changes

Schema changes always go through Alembic migration *files* — never raw `ALTER`.
Pre-go-live (no live data), make a schema change by **editing the existing
migration that owns the table and rebuilding the DB** (drop + `alembic upgrade
head`), not by appending a new corrective migration — appended fix-migrations
polluted the chain before (the phantom 031/032 episode). Dropping and rebuilding
the local DB is fine. This flips to append-only corrective migrations once there
is live data at go-live.

## Coding Rules

- Use Python 3.12+ and `uv` (`uv run ...` for commands; not Poetry, not pip).
- Ruff for linting and formatting checks.
- Keep module changes scoped to the subsystem being changed.
- Prefer explicit dataclasses and small functions over broad service objects.
- Do not commit `.env`, logs, data artifacts, caches, or XDF files.
- Unit tests should avoid a DB unless behavior requires one. DB-backed tests use
  `@pytest.mark.integration` and `TEST_DATABASE_URL`; suite lives in
  `tests/capture_tests/`.

## Working Style

Read the relevant module and tests before editing. Prefer small, direct changes
over broad refactors. Keep deferred systems deferred unless the user explicitly
reintroduces them: live safety/SQI semantics, broad FastAPI service, live
signal and ARC review screens in `web/`,
BLE/UWB hardware, cloud infrastructure, Kafka/Flink, and heavyweight external
signal-processing stacks.
