# CLAUDE.md - blackRabbit 1a

This file is the working context for AI agents and contributors in this repo.
It mirrors the canonical contract in `AGENTS.md` (root) — if they disagree,
`AGENTS.md` wins. It describes the current MVP, not a future regulated
deployment.

> Naming: the product is **blackRabbit**. The repo directory, Python packages
> (`capture.*`, `batch.*`), and DB name (`untitledplatform_1a_db`) still carry
> the legacy `untitled*` identifiers and are intentionally not renamed.
> "Untitled Biometric Platform", "Neurobiometric", "Consensai", and "UCSF" are
> dead names — do not reintroduce them.

## Product Frame

blackRabbit 1a is a local research-tool MVP for labs studying neuro-behavioral
sessions. It captures synchronized physiology and event context, keeps an
auditable local record, and supports post-session analysis.

It is not a therapy app, wellness product, clinical trial management system, or
regulated medical device. Regulated deployments can add governance workflows on
top of the core schema, but that is not the default 1a scope.

## Modalities

### APEX - Physiology Layer

APEX captures EEG, HRV, EDA, and respiration through Lab Streaming Layer (LSL).
The capture path writes raw or minimally transformed samples to TimescaleDB and
to a simultaneous XDF backup. Per-modality tables stay separate.

### ECHO - Context Layer

ECHO captures session context as LSL marker events. The 1a MVP supports manual
zone and marker events only. Hardware proximity systems are deferred.

### ARC - Agentic Response Convergence

ARC is the post-session convergence layer between ECHO anchors and APEX response
windows. It asks which physiological components responded around a contextual
event and persists reproducible baseline/config provenance. ARC runs after
capture; it does not replace or mutate raw APEX/ECHO records. It is implemented
in `batch/arc/` (preflight gate, processor, windows, models), and its session
entry points accept sponsor scope. ARC lifecycle gating and its complete
specification remain unfinished.

## Repo Layout

- `capture/` — data acquisition: `session_init`, `forwarder` (+ `stream_thread`),
  `echo_handler`, `watchdog`, `session_close`, `xdf`, `logger`.
- `capture/hardware/` — optional headless BrainFlow to LSL bridge
  (`blackrabbit-hardware`); publishes device signals, records nothing.
- `batch/` — everything post-capture: `batch/arc/` (ARC), `batch/reconciliation/`
  (XDF↔DB reconciliation + backfill), per-modality `batch/*_batch.py`.
- `config/settings.py` — all runtime config, loaded from `.env`, validated at import.
- `untitledplatform_1a_db/db/alembic/versions/` — the migration chain.
- `tests/capture_tests/` — the active test suite.

## Current Pipeline

1. `capture.session_init` validates inputs (before opening a DB connection),
   creates an active session, and writes one metadata row per modality.
2. `capture.forwarder` reads LSL streams, writes XDF first, then writes samples
   to TimescaleDB/Postgres. Each `StreamThread` owns its DB connection, inlet,
   and runtime state; `ForwarderEngine` owns the lifecycle.
3. `capture.echo_handler` records manual ECHO marker events from an LSL marker
   stream.
4. `capture.watchdog` can run the forwarder as a supervised subprocess.
5. `capture.session_close` reconciles XDF counts against DB counts, backfills
   gaps where possible, and closes or fails the session. ARC runs afterwards
   as an explicit step (`python -m batch.arc`).

## MVP Roadmap

Release state is tracked in `CHANGELOG.md`, `docs/release-audit-2026-10-13.md`
and `docs/backend-handoff.md`. The `docs/2R` audits describe the previous
implementation.

Phase 3b is baseline-in-batch: compute reproducible baseline records from the
complete post-session dataset rather than live monitoring. Phase 3b also
includes the SQI (Signal Quality Index) monitor: post-session signal quality
assessment per modality, flagging noisy or artifact-contaminated windows before
ARC processes them. (Baseline computation currently lives in
`batch/arc/processor.py`; standalone SQI/safety batch steps are not built yet.)

Phase 5b is ARC batch core: ECHO anchor filtering/clustering, APEX window
queries, baseline comparisons, convergence event contracts, and durable ARC
outputs.

Operator surface: capture and analysis run from the CLI. `web/` holds an
agent-first Next.js console for session reads, session creation and
capability-gated actions through a local model (contract:
`.correctless/specs/frontend-shell.md`; API contract: `docs/ui-integration.md`).

Deferred from the MVP: live safety monitor, live signal and ARC review screens
in `web/`, broad FastAPI app, MNE/Neurokit2 feature jobs, physical device
profiles and UWB proximity hardware (the BrainFlow bridge in `capture/hardware/`
ships only the synthetic profile), cloud infrastructure, Kafka/Flink, and full
regulatory workflows.

## Where To Look

- Release state and history: `CHANGELOG.md`, `docs/release-audit-2026-10-13.md`,
  `docs/backend-handoff.md`
- Operator UI: `web/` (agent-first Next.js console); contract in
  `.correctless/specs/frontend-shell.md`
- Historical audits of the previous implementation: `docs/2R/`
- Architecture: `docs/architecture.md`, `.correctless/ARCHITECTURE.md`
- Decisions log (authoritative): `docs/decisions.md`
- UI ↔ backend contract: `docs/ui-integration.md`
- Feature specs (test contract authority): `.correctless/specs/`

## Engineering Rules

- Keep the capture path single and simple: LSL -> XDF + DB.
- Never write directly to `audit_events`; database triggers own audit rows.
- Keep `lsl_timestamp` and `db_insert_time` separate everywhere.
- Keep per-modality tables separate.
- Use pseudonymous participant IDs only.
- Keep all runtime config in `config/settings.py` and `.env`.
- Never trigger batch work before `watermark_verified`; never bypass
  sponsor/site tenancy checks; never remove XDF reconciliation.
- Do not commit `.env`, data artifacts, logs, caches, or XDF files.
- Prefer small, tested changes over broad rewrites.

## Workflow & Decisions

- Spec-first (Correctless): `.correctless/specs/` are the contract authority and
  tests are derived from them.
- **Never hand-edit test files to make them pass.** Reconcile a failing test
  against the spec — fix the implementation, or upgrade the spec and regenerate
  the test (user-gated). If only a test change would fix it, stop and surface it.
- Record important decisions in `docs/decisions.md` (house format: Decision /
  Rationale / Code impact / Date) in the same task.

## Database Rules

The active migration chain is the source of truth (clean 001 → head
`030_arc_failure_alert_type`). `untitledplatform_1a_db/db/SCHEMA.md` documents
the chain, but migrations decide behavior. Optional governance migrations under
`optional_governance/` are reference material for deployments that need them.

Schema changes always go through Alembic migration *files* — never raw `ALTER`.
**Pre-go-live (no live data), make a schema change by editing the existing
migration that owns the table and rebuilding the DB** (drop +
`alembic upgrade head`), not by appending a new corrective migration. Dropping
and rebuilding the local DB is fine. This flips to append-only corrective
migrations once there is live data at go-live.

Every table that carries session data includes tenant identity (`site_id`,
`sponsor_id`) and pseudonymous subject identity where applicable. Application
queries must preserve those boundaries.

## Coding Conventions

- Python 3.12+.
- `uv` manages dependencies and commands (`uv run ...`) — not Poetry, not pip.
- Ruff handles linting and formatting.
- Pytest is the test runner; suite lives in `tests/capture_tests/`. DB-backed
  tests use `@pytest.mark.integration` and `TEST_DATABASE_URL`.
- DB driver is psycopg2 (a psycopg3 migration is contemplated, not started).
- Logs use `capture.logger.get_logger`.
- Prefer structured APIs and parameterized SQL.
- Keep literal table names in dynamic SQL from closed internal mappings.
- Keep comments short and useful.

## Contributor Workflow

Before implementing:

1. Read the relevant module and tests.
2. Confirm whether the request is code, docs, schema, or operational config.
3. Keep unrelated files out of the change.
4. Run the narrowest useful tests, then the full suite when behavior changes.

When in doubt, preserve the current local-research MVP shape and defer larger
product, clinical, cloud, or UI decisions.
