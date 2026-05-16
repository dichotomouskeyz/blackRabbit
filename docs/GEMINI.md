# GEMINI.md

## Role
Gemini is a maintenance + documentation agent.

Primary responsibilities:
- safe refactors
- JSON → TOML conversion
- dependency graph generation
- README regeneration
- documentation-as-code upkeep

Gemini is NOT:
- the architect
- a product strategist
- responsible for 1b infrastructure
- responsible for changing scope

---

# Current Priority

Focus:
# ARC convergence for the 1a MVP.

Current goals:
- ECHO/APEX synchronization
- temporal convergence windows
- live convergence events
- OpenBCI integration
- replayable simulated sessions
- investor-demoable workflows

Optimize for:
- simplicity
- reliability
- clarity
- local execution

NOT:
- scalability
- cloud infra
- orchestration systems
- generalized abstractions

---

# Project Summary

## APEX
Physiological streams:
- EEG
- HRV
- EDA
- respiration

## ECHO
Contextual events:
- manual LSL markers
- zones
- facilitator/context events

## ARC
Convergence layer.

ARC asks:
> when something happens in the environment, did the body respond?

ARC responsibilities:
- synchronize ECHO + APEX
- open W1/W2/W3 windows
- emit convergence events
- support visualization + replay

---

# Previous Phases

## Phase 0
Completed:
- VS Code workflow
- Poetry
- Docker
- local AI tooling
- architecture constraints
- local-only 1a strategy

## Phase 1
Completed:
- TimescaleDB/Postgres
- Alembic migrations
- hypertables
- audit triggers
- watermark architecture
- structured logging
- echo_events
- alert_events
- session metadata system

---

# Current Phase

## Phase 2 — Capture Layer
Current work:
- LSL ingestion
- lsl_forwarder.py
- session_init.py
- structured logging
- XDF reconciliation
- clock drift tracking
- ECHO marker ingestion
- ARC foundations

---

# Future Phases

## Phase 3
- live convergence
- websocket streaming
- safety monitoring
- SQI monitoring

## Phase 4
- convergence visualization
- replayable sessions
- coordinator UI
- investor demos

## Phase 5
- MNE
- Neurokit2
- ECP generation
- session summaries

## Phase 6
- hardening
- audit validation
- security pass
- demo prep

---

# Refactor Rules

Gemini may:
- improve readability
- reduce duplication
- improve naming
- improve structure
- improve imports/types
- reorganize configs/docs

Gemini must:
- preserve behavior
- prefer small diffs
- explain changed files
- recommend tests afterward

Do NOT:
- rewrite architecture
- redesign schema
- expand scope
- introduce unnecessary abstractions

---

# JSON → TOML Rules

Convert to TOML ONLY if:
- human-edited config
- algorithm params
- device profiles
- local settings
- session defaults

Keep JSON for:
- API payloads
- logs
- DB JSONB
- event serialization
- machine-generated data

Preferred:
- tomllib for reading
- readable sections
- update loaders/tests/docs together

---

# Dependency Graph Duties

Generate/update:
- docs/DEPENDENCY_GRAPH.md
- Mermaid graphs
- module dependency summaries

Track:
- entrypoints
- imports
- shared utilities
- config usage
- DB touchpoints
- circular dependencies

---

# README Duties

README should reflect:
- current Python files
- pyproject.toml
- Docker setup
- scripts
- tests
- current phase
- actual runnable commands

README should stay:
- practical
- current
- short
- runnable

---

# 1a Scope Boundary

## IN SCOPE
- local Docker
- TimescaleDB/Postgres
- direct DB writes
- WebSockets
- polling monitors
- OpenBCI integration
- replay systems
- TOML config

## OUT OF SCOPE
- Kafka
- Flink
- AWS
- MCP
- Neo4j deployment
- pgvector population
- autonomous agents
- orchestration systems
- cloud scaling

If work requires out-of-scope infra:
STOP and document the interface only.

---

# Non-Negotiables

Never:
- write directly to audit_events
- collapse timestamps
- expose participant identity
- hardcode config
- bypass watermark_verified
- use deprecated modality names

Always:
- use Alembic
- preserve pseudonymous IDs
- preserve structured logging
- preserve timestamp separation
- preserve ECHO/APEX/ARC naming

---

# Testing

After changes recommend:
```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
