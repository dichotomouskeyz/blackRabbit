# agent.md — Untitled Neurobiometric Platform 1a

This file is the operational contract for all AI-assisted development in this repository.

Its purpose is NOT to fully document the system.
Its purpose is to maintain:
- implementation focus
- architectural continuity
- regulatory integrity
- scope discipline
- phase awareness

If uncertain:
optimize for the current 1a MVP milestone, not future architecture elegance.

---

# 0. Current Priority

## ACTIVE IMPLEMENTATION TARGET
Current focus is:
# ARC convergence implementation for the 1a MVP.

The immediate goal is:
- real-time synchronization between ECHO and APEX
- local-first execution
- OpenBCI EEG integration
- believable convergence visualization
- replayable simulated sessions
- investor-demoable workflows

This is NOT:
- a production-scale intelligence platform
- generalized orchestration infrastructure
- a cloud-native system
- a multi-agent framework
- a 1b architecture implementation

Prefer:
- direct implementation
- clarity
- reliability
- demoability
over:
- abstraction
- scalability
- future-proofing
- infrastructure purity

---

# 1. What This Platform Is

This platform is a neurobehavioral convergence platform for experience-based and psychedelic clinical research.

The platform measures:
- physiological activity
- contextual events
- synchronized convergence between them

The system is intended to demonstrate:
- synchronized human-state modeling
- event-coupled physiological response analysis
- convergence detection across modalities

---

# 2. What 1a Is

1a is:
- local-first
- simulation-capable
- EEG-integrated
- investor-demoable
- disposable infrastructure

1a exists to:
- validate the concept
- demonstrate convergence
- support pitch competitions
- support research demonstrations
- create a believable operational prototype

1a will likely be rebuilt from scratch later for 1b.

Do NOT optimize for:
- scalability
- generalized infra
- distributed systems
- orchestration purity
- cloud deployment
- long-term maintainability

If a simpler implementation achieves the 1a goal:
choose the simpler implementation.

---

# 3. Three Modalities

## APEX — Physiological Layer
APEX handles:
- EEG
- HRV
- EDA
- respiration

Responsibilities:
- biosignal ingestion
- signal storage
- signal quality monitoring
- physiological state representation

APEX streams remain structurally independent during capture.

---

## ECHO — Contextual Layer
ECHO handles:
- contextual events
- behavioral events
- facilitator interactions
- environmental markers
- zone activity

1a MVP:
- manual LSL marker stream only

BLE/UWB hardware is deferred to 1b.

---

## ARC — Convergence Layer
ARC is the synchronized convergence engine.

ARC fuses:
# ECHO + APEX

ARC asks:
> when something happens in the environment, did the body respond?

ARC responsibilities in 1a:
- synchronize ECHO and APEX streams
- open temporal convergence windows
- compute lightweight convergence metrics
- emit live convergence events
- support replayable simulated sessions
- support convergence visualization

ARC does NOT include in 1a:
- advanced inference systems
- autonomous interpretation
- generalized intelligence agents
- cross-session learning
- cloud processing
- orchestration infrastructure

---

# 4. Current Active Subsystem

## ARC Foundations (ACTIVE)

Current implementation priorities:
- canonical ECHO event schema
- ARC convergence event object
- W1/W2/W3 temporal windows
- synchronized timestamp alignment
- ECHO event ingestion
- convergence event emission
- lightweight convergence scoring
- convergence visualization support

The goal is:
# believable synchronized convergence.

Not:
- publication-grade analytics
- full statistical rigor
- production scientific infrastructure

---

# 5. Previous Phase Summaries

## Phase 0 — Foundation ✅
Completed:
- VS Code workflow
- local AI tooling
- Docker setup
- Poetry dependency management
- repository structure
- sub-agent workflow
- architecture constraints
- local-only 1a strategy

Key decisions:
- no cloud
- no Kafka
- no Flink
- no MCP
- no agents in 1a
- simulation-first workflow

---

## Phase 1 — Environment + Schema ✅
Completed:
- TimescaleDB/Postgres stack
- Alembic migrations
- regulatory schema foundations
- hypertables for physiological streams
- audit trigger architecture
- alert_events
- echo_events
- session metadata system
- watermark processing model
- structured logging foundations
- pgvector placeholders
- compression policies

Core architecture established:
- append-only audit trail
- watermark-triggered batch flow
- per-modality hypertables
- pseudonymous participant IDs
- regulatory-safe schema structure

---

# 6. Current Phase

## Phase 2 — Capture Layer (ACTIVE)

Current work:
- LSL ingestion
- synthetic stream simulation
- lsl_forwarder.py
- session_init.py
- structured logging
- XDF reconciliation
- clock drift tracking
- ECHO marker ingestion
- ARC convergence foundations

Current goal:
- stable synchronized ingestion
- reliable local recording
- replayable sessions
- convergence-ready streams

---

# 7. Future Phase Summaries

## Phase 3 — Streaming
Real-time convergence:
- ECHO/APEX synchronization
- convergence windows
- live ARC events
- websocket streaming
- safety monitoring
- SQI monitoring

---

## Phase 4 — Interface
Coordinator-facing system:
- convergence visualization
- synchronized timelines
- replayable sessions
- live session interface
- investor demo workflows

---

## Phase 5 — Batch
Post-session analysis:
- MNE processing
- Neurokit2 processing
- convergence validation
- Event Composite Profiles (ECPs)
- session summaries

---

## Phase 6 — Hardening
Demo readiness:
- audit validation
- security review
- full simulated session tests
- pitch/demo preparation
- 1b migration planning

---

# 8. 1a Scope Boundary

## IN SCOPE
- local Docker infrastructure
- TimescaleDB/Postgres
- direct DB writes
- JSON serialization
- polling monitors
- WebSockets
- OpenBCI integration
- simulated sessions
- replay systems
- convergence visualization

---

## OUT OF SCOPE
- Kafka
- Flink
- AWS
- cloud infra
- Neo4j deployment
- MCP infrastructure
- generalized orchestration
- multi-agent systems
- pgvector population
- distributed processing
- autonomous intelligence layers

If a task requires anything above:
STOP.
Document it for 1b.
Do not implement it in 1a.

---

# 9. Regulatory Non-Negotiables

## Never:
- write directly to audit_events from application code
- collapse lsl_timestamp and db_insert_time
- expose real participant identity
- trigger batch before watermark_verified
- hardcode config values
- bypass sponsor/site tenancy
- bypass algorithm governance fields
- remove XDF reconciliation
- use deprecated modality names

---

## Always:
- use Alembic migrations
- use config/settings.py
- use structured JSON logging
- preserve audit integrity
- preserve timestamp separation
- preserve pseudonymous IDs
- preserve replayability

---

# 10. Coding Rules

## Backend
- Python 3.11+
- Poetry only
- pytest only
- Ruff formatting

---

## Frontend
- React
- introduced in Phase 4 only

---

## Logging
Every process must use:
capture/logger.py

Every log line includes:
- timestamp
- process_name
- log_level
- session_id (nullable)
- message

JSON format only.

---

## Config
All config comes from:
config/settings.py

Nothing hardcoded.
Ever.

---

# 11. Agent Behavior

## Always
- prioritize current milestone execution
- preserve scope discipline
- explain implementation decisions clearly
- prefer understandable code
- optimize for demo reliability
- maintain architectural continuity

---

## Never
- prematurely optimize infrastructure
- introduce generalized abstractions unnecessarily
- drift into 1b implementation
- over-engineer for scalability
- propose major refactors without necessity
- build invisible infrastructure with no 1a value

---

# 12. Operational Philosophy

This project is:
# a synchronized convergence demonstration system.

The objective is not to build the final architecture.

The objective is to prove:
- convergence is measurable
- synchronization is possible
- the pipeline works
- the system feels real
- the concept is compelling

Build toward:
- clarity
- synchronization
- demonstration
- reliability
- explainability

Not toward:
- maximal complexity
- theoretical perfection
- infrastructure completeness