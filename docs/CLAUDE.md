# CLAUDE.md — Untitled Neurobiometric platform 1a

This file is read by every AI agent that opens this repository.
It is the ground truth for what this platform is, how it works, and what the rules are.
Do not deviate from these constraints without explicit instruction from Jay.

---

## What This Platform Is

This platform is a regulatory-grade neuro-behavioral intelligence platform for psychedelic and experience-based clinical trials.

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

### APEX (Autonomous Physiological eXpression Pipeline)  — Brain-Body Signal Layer
- EEG, HRV, EDA, respiration
- Continuous biosignal capture via LSL
- APEX (Autonomous Physiological eXpression Pipeline) — brain-body biosignal processing layer. EEG, HRV, EDA, respiration. Versioned, reproducible, per-signal, no cross-signal normalization.

### ECHO (Event-Coupled Human Observatory) — Contextual Layer
- Interpersonal and environmental factors
- MVP: manual proximity zone logging via LSL Marker Stream only
- BLE/UWB hardware deferred to 1b
- ECHO (Event-Coupled Human Observatory) — behavioral event capture layer. Millisecond-aligned LSL timestamps. Zone entry, facilitator proximity, manual markers. Structurally independent from APEX during capture.

### ARC (Aligned Response Convergence) — Fusion Layer
- Combines APEX  + ECHO  into regulatory-grade output indices
- Efficacy, Safety, Expectancy, Synchrony
- convergence engine. When an ECHO event occurs, ARC asks: which APEX signals responded, how many, how fast? Multi-scale temporal windowing, convergence density, FDR control, Event Composite Profiles (ECPs).

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
- Postgres: sessions, audit_events, alert_events, echo_events
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

**9. Never refer to modalities as HUMeN, SONeM, or BEAM — canonical names are ECHO, APEX, ARC**

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




## Build Roadmap — 1a MVP Phases

**Target:** 1a MVP complete before September 16, 2026.
**Philosophy:** Build to learn, not just to ship. Understand what you built, not just that it works.

---

### Phase 0 — Foundation (Apr 22 → May 1) ✅
No code. All prep.

**Goal:** VS Code configured, Ollama + Qwen3.6 running locally, Claude Code CLI installed,
five sub-agents written (Orchestrator, Phase 1, Phase 2/3, Phase 4, Phase 5/6), CLAUDE.md
drafted, all architectural decisions documented, repo initialized, Poetry managing
dependencies, git branching strategy decided.

**Key decisions made:**
- No agent in 1a (pure pipeline)
- No audio capture in 1a
- Simulated LSL streams in 1a — real hardware deferred until clinical partner confirmed
- Compound-specific safety thresholds: literature values as placeholder, configurable via
  algorithm_params.yaml
- WebSocket over polling for real-time delivery
- JSON serialization in 1a (Avro in 1b when Kafka arrives)
- Poetry for dependency management across all of 1a
- Five sub-agent structure stored in .qwen/agents/
- Logging: JSON structured via shared logger, one file per process per session,
  never auto-deleted (audit trail)

---

### Phase 1 — Environment + Schema (May 1 → May 20) ✅ (in progress)
First real build. Infrastructure only.

**Goal:** Docker stack running locally, all database migrations created via Alembic, schema
documented, pre-commit hooks active, pytest configured, pgAdmin running, pyproject.toml
locked via Poetry.

**Docker stack:** TimescaleDB + Postgres + FastAPI stub + React stub via docker-compose.

**Migrations completed:**
- 001: TimescaleDB + pgvector extensions
- 002: eeg_samples hypertable (narrow row — one row per channel per sample)
- 003: compound_reference lookup table (7 compounds: psilocybin, lsd, ibogaine, mdma,
       5_meo_dmt, mescaline, dmt) — UI reads human names, DB stores lowercase identifiers
- 004: hrv_samples hypertable
- 005: eda_samples hypertable
- 006: respiration_samples hypertable
- 007: audit_events (append-only — triggers write only, application code cannot write directly)
- 008: alert_events (includes algorithm_name, algorithm_version, algorithm_parameters JSONB
       on every row — FDA requirement)
- 009: echo_events (source enum: manual | imu_derived, all rows manual in 1a)
- 010: pgvector columns on session_notes + alert_events, session_feature_vectors table
       (all NULL in 1a, populated in 1b)
- 012/013: TimescaleDB columnar compression + auto-compression policies (compress chunks
           older than 1 day)
- sessions table: status enum (pending | active | completed | aborted), batch_processed_at
                  column. Watermark fires on completed only.
- 014: participant_consent_log (Part 11 requirement — must exist before any real trial data)
- 015: schema_version_metadata (records app version + migration version at session creation)
- 017a: electronic_signatures (legally binding per Part 11 §11.50 — session close, dose
        administration, alert acknowledgment, consent. Includes signature_hash SHA-256
        column for tamper detection.)
- 017b: investigational_product_log (DEA chain of custody for Schedule I substances,
        gram by gram: receipt → preparation → administration → return → destruction)
- 018: adverse_event_log (CTCAE grading 1-5, relatedness, FDA/IRB reporting timestamps.
       Grade 4-5 SAEs require FDA reporting within 7 days per 21 CFR 312.32.)
- 019: session_signal_metadata (one row per modality per session — required before any
       biosignal samples written. Holds reference electrode, sampling freq, filters,
       device-specific fields per modality.)
- 020: audit triggers (two functions: audit_trigger_full_func for low-volume tables,
       audit_trigger_lightweight_func for biosignal hypertables — records metadata only,
       not full rows, to avoid doubling storage)
- 021: data_correction_and_amendment_log (Part 11 §11.10(e) — preserves original values,
       requires correction reason NOT NULL)
- 022: session_environment_log (set/setting covariates: temperature, light, music,
       facilitator count, session format, prep sessions — research asset, not FDA required)
- 023: indexes on session_id, site_id, sponsor_id, lsl_timestamp across all tables
- 024: watermark trigger identifies whether session is failed or done, and ready for batch processing

**Deferred migrations (not in 1a):** protocol_deviation_log, encryption columns,
SAE escalation log, export/disclosure log, data lock log, user role change log,
randomization/unblinding log, data query log, rater certification log,
audit_events partitioning, data access log, system_users + access log.

**Gate (before Phase 2):** All migrations apply cleanly to untitledplatform_test. audit_events
is append-only. Audit trigger fires on every insert. Application code cannot write to
audit_events. lsl_timestamp and db_insert_time are separate and never null on all tables.
session_signal_metadata table exists with required fields enforced.

---

### Phase 2 — Capture Layer (May 20 → June 10)
LSL comes online. First real data.

**Goal:** LSL forwarder writing to TimescaleDB, config loader working, watchdog running,
XDF backup writing, clock drift handled, structured logging across all processes.

**Key components:**
- config/settings.py — single source of all config, loaded from .env. Nothing hardcoded anywhere.
- capture/logger.py — shared JSON structured logging helper, imported by every process.
  Fields: process_name, timestamp, log_level, session_id (nullable), message.
- LSL stream simulator — synthetic EEG (256Hz), HRV (~1Hz), EDA (4-32Hz), respiration (~0.3Hz)
- lsl_forwarder.py — opens pylsl inlets, reads samples, injects metadata (session_id,
  participant_id, site_id, stream_type, device_id, lsl_timestamp, sample_count), serializes
  to JSON with versioned schema, writes directly to TimescaleDB (no Kafka in 1a). Handles
  DB connection drops by buffering locally. Records remote_clock offset at regular intervals
  (clock drift — non-optional for ibogaine 8-hour sessions).
- session_init.py — initializes session record, writes config_snapshot audit event at
  session start, writes one row per modality to session_signal_metadata, writes one row to
  schema_version_log (alembic_version, app_version, all library versions — read
  programmatically, nothing hardcoded).
- XDF backup — LSL Recorder runs alongside forwarder. On session close: row count in
  TimescaleDB compared against XDF. Backfill from XDF on DB interruption — chunks of ~1,000
  rows per commit (memory manageable, meaningful audit entries, resumable).
- Watchdog — systemd service file for lsl_forwarder.py. Every restart logged to audit_events.
- ECHO manual logging — LSL Marker Stream handler, events written to echo_events with
  correct lsl_timestamp.

**Gate (before Phase 3):** Forwarder writes all 4 modalities with separate timestamps.
No plaintext patient data in any table after simulated session. XDF row count matches
TimescaleDB. Device registry accepts/rejects correctly.

---

### Phase 3 — Streaming Layer (June 10 → June 30)
Safety and quality monitoring.

**Goal:** safety_monitor.py and sqi_monitor.py running as separate processes. WebSocket
complete. Coordinator alerted in real time on threshold breach.

**Key components:**
- WebSocket endpoint: WS /sessions/{id}/stream — sends live alert and SQI events to
  coordinator. Native FastAPI, no extra library. Connection manager handles
  connect/disconnect/reconnect.
- algorithm_params.yaml — all threshold values, versioned.
- safety_monitor.py — separate process from forwarder. Polls TimescaleDB, compares values
  against participant baseline and compound thresholds, fires to alert_events on breach,
  includes algorithm_name/version/parameters on every alert row (FDA requirement), sends
  alert via WebSocket. Ibogaine cardiac flag (R-R interval monitoring) is the most
  sensitive threshold — safety-critical.
- sqi_monitor.py — separate process. Computes spectral edge frequency, impedance checks,
  leads-off detection for EEG. Writes sqi_flag per sample. Sends quality status via
  WebSocket.
- Note: participant_id can be NULL at session creation — Start Recording button in UI is
  disabled until provided.

**Gate (before Phase 4):** Synthetic cardiac anomaly fires alert in alert_events AND
delivers via WebSocket. SQI flag set correctly AND arrives via WebSocket. All three
processes run simultaneously without interference.

---

### Phase 4 — Session Interface (July 1 → Aug 1)
The human-facing layer.

**Goal:** FastAPI backend complete, CORS configured, React coordinator interface functional.
Watermark verification logic built. Full Postman collection green.

**Key components:**
- FastAPI with role-based auth (coordinator, admin), CORS (explicit origin only, no
  wildcard in production), WHERE sponsor_id = ? on every query (data tenancy enforcement).
- capture/signatures.py — compute_signature_hash(record_dict). SHA-256 over
  sort_keys=True JSON serialization. Called before any electronic_signatures row is inserted.
  Tamper detection: recomputing hash against modified record produces different value.
- Routes: sessions CRUD, alert acknowledgment, consent (must exist before Start Recording),
  adverse events (Grade 4-5 auto-creates SAE escalation row with deadline_at), SAE
  escalation lifecycle, protocol deviation, investigational product chain of custody,
  system user management, data correction/amendment, data lock/unlock, export disclosure,
  data query management, rater certifications, SQI, ECHO, devices.
- Data access logging — middleware/dependency injection on every route that queries patient
  data. Writes to data_access_log: actor_id, table_name, query_description, row_count,
  session_id. No route can bypass this.
- Postgres role architecture (required before UCSF):
  - app_role: INSERT only on audit tables (no UPDATE/DELETE ever)
  - coordinator_role: INSERT on session and event tables, no access to system_users or
    data_access_log
  - readonly_role: reporting queries only
  - Superuser credentials vaulted, never used in production paths
- Watermark verification (watermark_check.py) — runs on session close before batch trigger.
  Queries last lsl_timestamp per stream, compares against session end time, flags gaps,
  writes watermark_verified or watermark_failed to audit_events. Batch blocked on failure.
- React coordinator interface: session start screen, live alert feed (WebSocket,
  severity color-coded), SQI status panel (green/yellow/red per stream), device connection
  status, ECHO zone buttons, session timer, alert acknowledgment flow, session close flow.
  AI-generated content visually separate from audit trail in UI.
- Error states handled: browser close mid-session, device drop/reconnect, DB write failure
  (forwarder buffers + retries), forwarder crash (watchdog restarts + notifies coordinator).

**Gate (before Phase 5):** All API routes pass auth and tenancy tests. Watermark blocks
batch on failed verification. Watermark event written to audit_events.

---

### Phase 5 — Batch Layer + Integration (Aug 1 → Aug 25)
Post-session processing and full pipeline test.

**Goal:** MNE + Neurokit2 batch jobs running, session summary generated, full end-to-end
simulated session passes without errors.

**Key components:**
- Aborted session batch path — sessions where dose was administered but session aborted are
  clinically significant under ITT analysis. Reduced path: safety event summary, ECHO
  timeline, partial biosignal features, mandatory protocol_deviation_log entry. Not optional.
- EEG batch job (MNE): band power (delta/theta/alpha/beta/gamma), network coherence,
  entropy measures → Postgres.
- HRV/EDA batch job (Neurokit2): HRV frequency domain, vagal tone, EDA tonic/phasic
  decomposition (cvxEDA), event-locked responses aligned to ECHO events → Postgres.
- ECHO contextual processing: proximity zone durations, facilitator presence timeline,
  contextual event sequence, zone distribution.
- Safety event summary, session summary (structured JSON to disk + Postgres).
- ECHO IMU proximity batch job — conditional on UCSF pilot device IMU confirmation.
- Full E2E simulated session test run (30 min): start → streams → synthetic safety alert
  → WebSocket delivery + acknowledgment → ECHO events → session close → watermark pass
  → batch trigger → summary generated → complete audit trail. Run twice — both must produce
  identical audit trail structure.

**Gate (before Phase 6):** Full E2E simulated session passes without errors. Audit trail
complete and unbroken. No plaintext anywhere in DB after full session. E2E run twice.

---

### Phase 6 — Hardening + Demo Prep (Aug 25 → Sep 15)
Make it presentable and defensible.

**Goal:** Error states handled, audit trail validated, security pass done, first demo
session run, demo video recorded, roadmap to 1b documented.

**Key tasks:**
- Complete SCHEMA.md (every table, every column, with reasoning)
- Complete DECISIONS.md (every crossroads decision with reasoning)
- Complete migration_1a_to_1b.md (every 1a component mapped to 1b equivalent)
- Security pass: no real credentials in repo, .env never committed, no participant identity
  in any synced table
- Audit trail replay test: confirms complete and tamper-evident trail
- First demo session with another person as coordinator
- Demo video (screen capture of full simulated session, start to summary)
- Plain English explanation of what 1a demonstrates and what 1b adds

**Open questions blocking before UCSF:**
- UCSF pilot hardware confirmation (does not block Phase 2 — simulator covers MVP)
- Clinical collaborator for safety threshold ownership
- Session summary exact format and delivery path (resolve in Phase 5)
- 1a → 1b data continuity migration path

---

## Deferred to 1b (Intelligence Layer)
Neo4j knowledge graph, Kafka (agent coordination + forwarder), Flink (replaces Python
monitoring scripts), AWS (replaces local DBs — schemas unchanged), MCP layer over
Untitled_platform data stores, APEX  agent, ECHO  context agent, attribution agent, cross-trial
comparison, literature synthesis, hypothesis generation, researcher interface, high density
EEG (64+ channel), pupillometry, BLE/UWB proximity, pgvector embeddings populated.

---

## Known Issues / Hard Requirements Before UCSF
1. Postgres role architecture — superuser can delete from audit tables. Required before any
   real session. Implement in Phase 4.
2. Aborted sessions must trigger batch processing — current watermark logic fires on
   completed only. Fix in Phase 5.
3. audit_trigger_smart_func — Migration 012 trigger function in codebase must match live
   DB version (COALESCE + TG_TABLE_NAME detection + NULL exception handler).
4. row_to_json PII policy — safe now (pseudonymous IDs only). If any table ever receives
   real PII, add JSONB `-` column exclusion before that migration runs.
5. Hypertable compression + backfill — compressed chunks cannot be written to without
   decompressing first. Document decompress → backfill → recompress procedure before first
   real session.