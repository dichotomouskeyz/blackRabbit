# CLAUDE.md - Untitled Biometric Platform 1a

This file is the working context for AI agents and contributors in this repo.
It describes the current MVP, not a future regulated deployment.

## Product Frame

Untitled Biometric Platform 1a is a local research-tool MVP for labs studying
neuro-behavioral sessions. It captures synchronized physiology and event context,
keeps an auditable local record, and supports post-session analysis.

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
capture; it does not replace or mutate raw APEX/ECHO records.

## Current Pipeline

1. `capture.session_init` creates an active session and writes one metadata row
   per modality.
2. `capture.forwarder` reads LSL streams, writes XDF first, then writes samples
   to TimescaleDB/Postgres.
3. `capture.echo_handler` records manual ECHO marker events from an LSL marker
   stream.
4. `capture.watchdog` can run the forwarder as a supervised subprocess.
5. `capture.session_close` reconciles XDF counts against DB counts, backfills
   gaps where possible, closes or fails the session, and invokes ARC
   post-session processing.

## MVP Roadmap

Phase 2 is the capture layer: session init, LSL forwarder, ECHO marker capture,
XDF backup, clock drift logging, watchdog lifecycle, and session close.

Phase 3b is baseline-in-batch: compute reproducible baseline records from the
complete post-session dataset rather than live monitoring. Phase 3b also
includes the SQI (Signal Quality Index) monitor: post-session signal quality
assessment per modality, flagging noisy or artifact-contaminated windows before
ARC processes them.

Phase 5b is ARC batch core: ECHO anchor filtering/clustering, APEX window
queries, baseline comparisons, convergence event contracts, and durable ARC
outputs.

Phase 4b is a thin user surface: CLI/notebook workflows for researchers. A full
web app is deferred.

Deferred from the MVP: live safety monitor, WebSocket coordinator UI, React
frontend, broad FastAPI app, MNE/Neurokit2 feature jobs, BLE/UWB hardware,
cloud infrastructure, Kafka/Flink, and full regulatory workflows.

## Engineering Rules

- Keep the capture path single and simple: LSL -> XDF + DB.
- Never write directly to `audit_events`; database triggers own audit rows.
- Keep `lsl_timestamp` and `db_insert_time` separate everywhere.
- Keep per-modality tables separate.
- Use pseudonymous participant IDs only.
- Keep all runtime config in `config/settings.py` and `.env`.
- Add schema changes only through Alembic migrations.
- Do not commit `.env`, data artifacts, logs, caches, or XDF files.
- Prefer small, tested changes over broad rewrites.

## Database Rules

The active migration chain is the source of truth.
`untitledplatform_1a_db/db/SCHEMA.md` documents that chain, but migrations
decide behavior. Optional governance migrations under `optional_governance/`
are reference material for deployments that need them.

Every table that carries session data includes tenant identity (`site_id`,
`sponsor_id`) and pseudonymous subject identity where applicable. Application
queries should preserve those boundaries.

## Coding Conventions

- Python 3.12+.
- `uv` manages dependencies and commands.
- Ruff handles linting and formatting.
- Pytest is the test runner.
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
