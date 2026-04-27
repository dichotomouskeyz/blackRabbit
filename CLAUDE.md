# CLAUDE.md — Consensai 1a

This file is read by every AI agent that opens this repository.
It is the ground truth for what Consensai is, how it works, and what the rules are.
Do not deviate from these constraints without explicit instruction from Jay.

---

## What Consensai Is

Consensai is a regulatory-grade neuro-behavioral intelligence platform for psychedelic and experience-based clinical trials.

### It is NOT
- A therapy app
- A general wellness platform
- A conventional pharmacological data logger

### It IS
- Scientific instrumentation for a field that has never had a measurement framework
- Regulatory-grade evidence infrastructure for psychedelic research
- The data foundation for trials at UCSF and beyond

**Key compounds:** psilocybin, LSD, ibogaine, MDMA

**Core principle:** Every architectural decision flows from regulatory integrity. If a decision trades regulatory integrity for convenience, it is wrong.

---

## Three Modalities

### SONeM — Brain-Body Signal Layer
- EEG, HRV, EDA, respiration
- Continuous biosignal capture via LSL

### HUMeN — Contextual Layer
- Interpersonal and environmental factors
- MVP: manual proximity zone logging via LSL Marker Stream only
- BLE/UWB hardware deferred to 1b

### Biometric Ground Truth — Fusion Layer
- Combines SONeM + HUMeN into regulatory-grade output indices
- Efficacy, Safety, Expectancy, Synchrony

---

## Four-Stage Pipeline

All data flows through exactly one path.

### This is NOT a Lambda architecture
- No dual-path processing
- No speculative batch runs
- A validated complete record must exist before any batch processing begins

### The four stages

**Stage 1 — Capture (LSL)**
- pylsl inlets receive all biosignal streams
- lsl_forwarder.py writes directly to TimescaleDB (1a only)

**Stage 2 — Streaming**
- safety_monitor.py runs as a separate process, polls TimescaleDB
- sqi_monitor.py runs as a separate process, polls TimescaleDB
- Alerts and SQI flags delivered to coordinator via WebSocket

**Stage 3 — Ingestion/Storage**
- TimescaleDB: all biosignal hypertables
- Postgres: sessions, audit_events, alert_events, humen_events
- XDF file: local backup written simultaneously, reconciliation source

**Stage 4 — Post-Session Batch**
- Triggers ONLY after watermark_verified event is written to audit_events
- MNE: EEG feature extraction
- Neurokit2: HRV/EDA feature extraction
- Session summary written to Postgres and local disk

### The check
Before writing any data handling code, ask: does this respect the single-path rule?
If a task involves processing data before a complete validated record exists — stop and ask Jay.

---

## 1a vs 1b — Scope Boundary

**1a is local only. No cloud. No Kafka. No Flink. No AWS. No agents.**
If a task requires anything in the OUT OF SCOPE list — stop. Document the interface and defer.

### IN SCOPE — 1a
- Direct DB write (no message broker)
- Polling loop for safety and SQI monitoring
- TimescaleDB + Postgres running locally in Docker
- Postgres triggers for audit trail
- JSON serialization
- Neo4j knowledge graph: designed and documented, NOT deployed
- pgvector columns: planted (all NULL), NOT populated

### OUT OF SCOPE — Defer to 1b
- Kafka / AWS MSK (message broker)
- Apache Flink (stream processing)
- AWS Timestream, RDS, QLDB, S3, IAM (cloud infrastructure)
- Avro serialization
- Neo4j deployment
- pgvector population
- Any intelligence layer agent
- Any A2A coordination
- BLE/UWB hardware

### The check
Before starting any task, ask: does this require anything in the OUT OF SCOPE list?
If yes — stop, tell Jay, document the interface, move on.

---

## Regulatory Constraints — Non-Negotiable

These exist because of 21 CFR Part 11 and FDA requirements for clinical trial software.
Violating any of these is not a code smell — it is a compliance failure.

### The rules

**1. Audit trail is database-trigger-only**
- Application code NEVER writes directly to audit_events
- Only database triggers write to audit_events
- No exceptions

**2. Timestamps are always separate**
- lsl_timestamp and db_insert_time are always distinct columns
- They must never be equal, derived from each other, or collapsed into one field

**3. Algorithm governance on every alert**
- Every row in alert_events must include: algorithm_name, algorithm_version, algorithm_parameters (JSONB)
- No exceptions

**4. Pseudonymous IDs only**
- Real participant identity never appears in any table that could be synced beyond local Postgres
- participant_id is always a pseudonymous token

**5. Data tenancy on every table**
- site_id and sponsor_id appear on every table
- WHERE sponsor_id = ? on every API query — no exceptions

**6. Batch only after watermark_verified**
- Batch jobs never trigger unless watermark_verified is written to audit_events first
- If watermark_failed: batch is blocked, coordinator is alerted

**7. XDF backup is not optional**
- Written in parallel with TimescaleDB at all times
- It is the reconciliation source if DB writes fail

**8. Clock drift is always recorded**
- lsl_forwarder.py records remote_clock_offset values at regular intervals
- Non-optional for ibogaine 8-hour sessions

### The check
Before writing any code that touches data storage or alert logic, ask:
- Does this write to audit_events directly from app code? → STOP
- Does this collapse lsl_timestamp and db_insert_time? → STOP
- Does this fire an alert without algorithm governance columns? → STOP
- Does this expose real participant identity? → STOP
- Does this trigger batch before watermark_verified? → STOP

---

## Database Rules

### Always
- Migrations via Alembic only — never modify schema outside a migration file
- Narrow row format for EEG — one row per channel per sample
- Per-modality hypertables — each biosignal has its own table
- All config from config/settings.py — nothing hardcoded

### Never
- Modify schema outside a migration file
- Collapse modality tables
- Populate pgvector columns in 1a — they are planted, not used
- Hardcode any DB URL, port, stream name, or credential

### The check
Before any schema change: is there an Alembic migration file for this?
If no — write the migration first, then proceed.

---

## Five Agents — Scope and Responsibilities

Each agent has a tightly scoped role. No agent operates outside its scope.
When activating an agent, load CLAUDE.md first, then state which agent you are invoking.

### Schema Architect
**Does:**
- Writes and reviews all Alembic migrations
- Writes and maintains db/SCHEMA.md
- Ensures all regulatory column requirements are met on every table

**Never does:**
- Generates application code
- Touches capture, streaming, or API layer

### Pipeline Builder
**Does:**
- Writes lsl_forwarder.py, session_init.py, safety_monitor.py, sqi_monitor.py
- Writes the LSL stream simulator
- Ensures all config comes from config/settings.py
- Ensures all processes use the shared logging helper from capture/logger.py

**Never does:**
- Touches schema or migrations
- Writes API routes or auth logic

### Compliance Reviewer
**Does:**
- Reviews any code that touches audit_events, alert_events, or the sessions table
- Verifies algorithm governance columns are present on every alert row
- Verifies triggers are the only write path to audit_events

**Never does:**
- Generates new features
- Writes migrations
- This agent is review-only

### API and Auth Builder
**Does:**
- Writes all FastAPI routes, middleware, and auth logic
- Enforces WHERE sponsor_id = ? on every database query
- Configures CORS — never wildcard in production
- Implements role-based auth — coordinator and admin roles only

**Never does:**
- Touches capture layer or database schema
- Writes migrations

### Documentation Writer
**Does:**
- Writes and maintains README.md, docs/DECISIONS.md, docs/migration_1a_to_1b.md
- Keeps db/SCHEMA.md complete and current

**Never does:**
- Generates code of any kind

---

## Coding Conventions

### Language
- Python 3.11+ for all backend
- React for frontend — Phase 4 only, not before

### Dependencies
- Poetry only — pyproject.toml is source of truth
- Never use pip install directly
- To add a package: poetry add [package]
- To add a dev package: poetry add --group dev [package]

### Formatting
- Python: Ruff (formatOnSave is on)
- JS/JSX: Prettier (formatOnSave is on)

### Logging
- Every process imports the shared logger from capture/logger.py
- Every log line must include: timestamp, process name, log level, session_id (nullable), message
- JSON structured format only

### Config
- Everything from config/settings.py which loads from .env
- Nothing hardcoded anywhere
- If required config is missing: fail loudly with a clear error before doing anything else

### Testing
- pytest only
- Tests live in tests/
- Every new script gets a test before it is considered done

### Git
- Commit prefixes: feat:, fix:, docs:, test:, refactor:
- Never commit directly to main
- All work on feature branches — merge only when task is complete and tested
- Never commit .env files or secrets

---

## The Never-Do List

Hard stops. If a task requires any of the following — stop immediately and ask Jay.

- Never write directly to audit_events from application code — triggers only
- Never collapse modality tables — EEG, HRV, EDA, respiration each have their own table, always
- Never expose real participant identity in any synced data
- Never trigger batch processing before watermark_verified is written
- Never hardcode any config value — no DB URLs, ports, or stream names in code
- Never build 1b infrastructure in 1a — no Kafka, Flink, or AWS services
- Never populate pgvector columns in 1a — planted, not used
- Never commit .env files or secrets
- Never collapse lsl_timestamp and db_insert_time into one field
- Never process data before a complete validated record exists (no Lambda architecture)

---

## Four-Tool Workflow

| Task | Tool |
|------|------|
| Planning, architecture, learning, regulatory reasoning | Claude.ai |
| Writing a single script, migration, config file | Qwen3.6 in VS Code (Continue) |
| Multi-file refactor, touching 5+ files at once | Claude Code CLI |
| Reviewing AI output before committing | Jay, in VS Code |
| Regulatory / audit / safety logic decisions | Claude.ai first, then implement |
| Debugging something broken | Qwen3.6 first, Claude.ai if stuck |

### How to load this file in each tool
- **Claude Code:** reads CLAUDE.md automatically from repo root on every session
- **Qwen in Continue:** type @CLAUDE.md in the Continue chat input at the start of every session before giving any task
- **Claude.ai:** paste relevant sections when needed for planning sessions

---

## Working with Jay

Jay is a neuroscience undergraduate building this iteratively while learning software engineering.

### Always
- Explain concepts as you go — not just what to do, but why and what it means
- Treat teaching as part of every technical step
- Never skip explanation in favor of speed

### Never
- Assume Jay knows why something works — explain it
- Generate code without explaining what it does and why it's structured that way


