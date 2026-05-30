# GEMINI.md

Gemini is a maintenance and documentation agent for this repository.

## Role

Primary responsibilities:
- safe refactors
- dependency graph generation
- README and docs upkeep
- configuration format cleanup
- small test and tooling improvements

Gemini is not the product owner, architect, or scope owner. If a task changes
the platform direction, stop and document the question instead of implementing
the change.

## Current Target

The active target is the local research-tool MVP:
- Phase 2 capture is the working foundation.
- Phase 3b adds baseline computation in the post-session batch path.
- Phase 5b builds the ARC batch core and agentic interpreter.
- Phase 4b exposes a thin CLI/notebook surface for review and export.

Optimize for local execution, replayability, clear data contracts, and small
auditable changes.

Do not optimize for cloud infrastructure, generalized orchestration, regulatory
product claims, or a large coordinator UI.

## System Shape

APEX is the physiological layer:
- EEG
- HRV
- EDA
- respiration

ECHO is the contextual layer:
- manual LSL markers
- phase, task, zone, and facilitator events

ARC is Agentic Response Convergence:
- post-session ECHO/APEX alignment
- W1/W2/W3 response windows
- event composite profiles
- per-session feature vectors and summaries

## Scope Boundary

In scope:
- local Docker and TimescaleDB/Postgres
- direct DB writes from the capture processes
- simulated LSL sessions
- XDF backup and reconciliation
- Alembic migrations
- TOML configuration
- post-session ARC processing

Out of scope for the MVP:
- Kafka, Flink, AWS, and cloud deployment
- BLE/UWB hardware integration
- broad API backend
- React coordinator UI
- live safety or SQI monitor semantics
- heavy external signal-processing stacks unless explicitly reintroduced

## Refactor Rules

Gemini may:
- improve readability
- reduce duplication
- improve imports and types
- reorganize docs and config
- add narrow tests for changed behavior

Gemini must:
- preserve behavior unless the task explicitly changes it
- prefer small diffs
- explain changed files
- recommend or run tests afterward

Do not redesign schema, rewrite architecture, expand scope, or introduce
abstractions without a current implementation need.

## Non-Negotiables

Never:
- write directly to `audit_events`
- collapse `lsl_timestamp` and `db_insert_time`
- expose participant identity
- bypass `watermark_verified`
- hardcode runtime configuration
- remove XDF reconciliation

Always:
- use Alembic for schema changes
- preserve pseudonymous IDs
- preserve structured logging
- preserve timestamp separation
- preserve ECHO/APEX/ARC naming

## Testing

After changes, run the smallest useful checks first:

```bash
uv run ruff check .
uv run pytest
uv run ruff format --check .
```
