# Architecture

blackRabbit 1a is a local research capture and post-session
analysis system.

## Runtime Shape

- `capture.session_init` creates an active session and modality metadata.
- `capture.forwarder` reads LSL biosignal streams and writes XDF before DB.
- `capture.echo_handler` records manual ECHO marker events.
- `capture.watchdog` supervises the forwarder process when used.
- `capture.session_close` reconciles XDF and DB counts, backfills gaps, closes
  or fails the session, and runs ARC post-session processing.

## Storage

- TimescaleDB/Postgres is the local source for queryable records.
- XDF is the local continuity backup and reconciliation source.
- Alembic migrations are the schema source of truth.
- Optional governance migrations are reference material, not part of the active
  default chain.

## Stub Packages

- `ingestion/` and `storage/` are included in the packaged project but are not
  part of the active capture pipeline.
- `ingestion/` contains empty modality stubs plus local safety/SQI process
  placeholders.
- `storage/` contains empty DB/schema placeholders.
- Active capture behavior remains under `capture/`; these stubs should not be
  treated as alternative ingestion or persistence implementations.

## Analysis

ARC means Agentic Response Convergence. ARC runs after capture over complete
session records. It does not write during capture and does not replace raw APEX
or ECHO tables.

Deferred systems include live safety/SQI monitoring, full API/UI surfaces, cloud
infrastructure, and external feature libraries.

## Agent Surfaces

Root `AGENTS.md` is the canonical AI-agent contract. `.codex/` and `.claude/`
are tool-specific compatibility surfaces. Local model tooling is intentionally
agent-neutral until a coding-agent stack is chosen.
