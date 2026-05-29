# AI Agent Contract

This file is the operational contract for AI-assisted development in this
repository. It preserves implementation focus and scope discipline; it is not a
complete architecture document.

## Current Priority

The current target is a local research-tool MVP for synchronized physiological
capture and post-session convergence analysis.

Prioritize:
- stable Phase 2 capture
- replayable simulated sessions
- XDF backup and reconciliation
- post-session ARC analysis
- documentation that reflects the code that exists

Do not drift into cloud infrastructure, production product claims, a broad UI,
or generalized orchestration.

## Platform Layers

APEX is the physiological layer:
- EEG
- HRV
- EDA
- respiration

ECHO is the contextual layer:
- manual LSL marker stream
- phase, task, zone, and facilitator events

ARC is Agentic Response Convergence:
- ECHO/APEX alignment
- W1/W2/W3 response windows
- event composite profiles
- batch summaries and feature vectors

## MVP Phase Map

Phase 2 is the capture foundation:
- session initialization and closeout
- LSL forwarder
- structured logging
- ECHO marker ingestion
- XDF backup and reconciliation
- watchdog process supervision

Phase 3b is baseline-in-batch:
- compute baselines after capture
- persist baseline records
- keep live monitor semantics deferred

Phase 5b is ARC batch:
- process complete post-session records
- generate convergence artifacts
- provide an agentic interpretation layer over deterministic outputs

Phase 4b is the thin operator surface:
- CLI/notebook workflows
- review and export
- no large frontend commitment by default

## Scope Boundary

In scope:
- local Docker infrastructure
- TimescaleDB/Postgres
- direct DB writes from local processes
- TOML configuration
- Alembic migrations
- simulated sessions
- local reproducibility

Deferred unless explicitly reintroduced:
- real-time safety monitor behavior
- live SQI monitor behavior
- broad FastAPI service
- React coordinator UI
- BLE/UWB hardware integration
- cloud deployment
- Kafka/Flink-style streaming infrastructure
- heavyweight signal-processing stacks

## Non-Negotiables

Never:
- write directly to `audit_events`
- collapse `lsl_timestamp` and `db_insert_time`
- expose real participant identity
- trigger batch work before `watermark_verified`
- bypass sponsor/site tenancy checks
- remove XDF reconciliation

Always:
- use Alembic migrations
- use `config/settings.py` for runtime configuration
- use structured JSON logging
- preserve pseudonymous IDs
- preserve replayability
- keep ECHO/APEX/ARC terminology current

## Coding Rules

Backend:
- Python 3.12+
- `uv` for local commands
- `pytest` for tests
- Ruff for linting and formatting checks

Configuration:
- environment variables are surfaced through `config/settings.py`
- human-edited algorithm or runtime config should be TOML
- DB payloads, logs, and event serialization may remain JSON/JSONB

## Agent Behavior

Prefer direct, understandable changes. Avoid broad refactors unless the current
task needs them. When behavior changes, add or update focused tests. When docs
change, ensure commands and phase names match the current repository.
