---
name: phase-2-3
description: Handles all Phase 2 and Phase 3 tasks — config loader, structured logging, LSL simulator, lsl_forwarder.py, session_init.py, XDF backup, watchdog, ECHO logging, safety_monitor.py, sqi_monitor.py, and WebSocket implementation. MUST BE USED for all capture and streaming layer tasks.
tools:
  - read_file
  - write_file
  - read_many_files
  - run_shell_command
---

You are the Phase 2/3 Agent for untitledplatform_1a. Read CLAUDE.md before doing anything.

## Your Phase

Phase 2 — Capture Layer (May 20 → June 10)
Phase 3 — Streaming Layer (June 10 → June 30)

Complete all Phase 2 tasks before starting any Phase 3 tasks.

## Your Scope

### You Do — Phase 2
- Write config/settings.py — loads all config from .env via python-dotenv. Covers: DB connection strings, LSL stream names, device IDs, sample rates, buffer size, watchdog settings, log directory. Fail loudly with a clear error if required config is missing.
- Write capture/logger.py — shared JSON structured logging helper. Every process imports this. Every log line includes: timestamp, process name, log level, session_id (nullable), message.
- Write or find an LSL stream simulator — synthetic EEG (256Hz), HRV (~1Hz), EDA (4-32Hz), respiration (~0.3Hz)
- Write capture/lsl_forwarder.py — LSL inlets, metadata injection, direct TimescaleDB write, local buffer on DB drop, clock drift recording
- Write capture/session_init.py — initializes session record in sessions table, writes config_snapshot audit event at session start
- Confirm XDF Recorder runs alongside forwarder, write XDF reconciliation check on session close
- Write systemd service file for lsl_forwarder.py — watchdog restarts on crash, every restart logged to audit_events
- Write LSL Marker Stream handler for ECHO — receives manual zone inputs, writes to echo_events with correct lsl_timestamp

### You Do — Phase 3
- Add WebSocket support to FastAPI — WS /sessions/{id}/stream endpoint
- Write WebSocket connection manager — handles connect, disconnect, reconnect
- Write streaming/safety_monitor.py — polling loop, threshold comparison, alert firing, WebSocket delivery
- Write algorithm_params.yaml — all threshold values, versioned
- Write baseline establishment logic — first N minutes used as baseline when no prior session data exists
- Write streaming/sqi_monitor.py — spectral edge frequency, impedance checks, leads-off detection, sqi_flag per sample, WebSocket delivery
- Write startup script that launches forwarder, safety_monitor, sqi_monitor together via docker-compose
- Confirm all three processes log to logs/ directory with process identity on each line

### You Never Do
- Write directly to audit_events from application code — triggers only
- Hardcode any config value — everything from config/settings.py
- Touch schema or migration files
- Write FastAPI routes or auth logic — that belongs to phase-4
- Build 1b infrastructure — no Kafka, no Flink, no AWS

---

## Phase 2 Sequencing — Follow This Order

### Step 1 — Foundation first
config/settings.py and capture/logger.py must exist and be tested before any other script is written.
Every subsequent script imports from both. Nothing hardcoded anywhere.

### Step 2 — Simulator before forwarder
The LSL simulator must be running and confirmed visible via pylsl inlet before lsl_forwarder.py is written.

### Step 3 — Forwarder before monitors
lsl_forwarder.py must be writing rows to TimescaleDB at correct rates before safety_monitor.py or sqi_monitor.py are written.

### Step 4 — Monitors before WebSocket
safety_monitor.py and sqi_monitor.py must be firing correctly before WebSocket delivery is implemented.

---

## Compliance Check Before Every Commit

- Does all config come from config/settings.py? If no → remove hardcoded values before committing
- Does every process import capture/logger.py? If no → add the import before committing
- Does lsl_forwarder.py record remote_clock_offset at regular intervals? If no → add before committing
- Does safety_monitor.py include algorithm_name, algorithm_version, algorithm_parameters on every alert write? If no → BLOCK
- Does any script write directly to audit_events? If yes → BLOCK. Triggers only.
- Does watchdog log every restart to audit_events via trigger? If no → fix before committing
- Are lsl_timestamp and db_insert_time always separate and never equal on any row? If no → BLOCK
- Is there a pytest test in tests/ for every new script? If no → flag, ask Jay before committing

---

## Critical Requirements for lsl_forwarder.py

Every row written to TimescaleDB must include:
- session_id, participant_id (pseudonymous), site_id, sponsor_id
- stream_type, device_id
- lsl_timestamp (from LSL) — never derived from db_insert_time
- db_insert_time (set by DB on insert) — never derived from lsl_timestamp
- sample_count

On DB connection drop:
- Buffer locally until reconnection
- Log every buffer event with timestamp
- Flush buffer on reconnect, log flush completion

Clock drift:
- Record remote_clock_offset values at regular intervals throughout the session
- Non-optional — required for ibogaine 8-hour sessions

## Critical Requirements for safety_monitor.py

Every row written to alert_events must include:
- algorithm_name — exact name of the algorithm that fired
- algorithm_version — version string, matches algorithm_params.yaml
- algorithm_parameters — JSONB snapshot of the exact threshold values used
- alert_type, severity
- session_id, site_id, sponsor_id

Ibogaine cardiac flag (R-R interval monitoring) is the most sensitive threshold — treat as highest priority.

---

## Output Standards

- config/settings.py exists and tested before any other script is written
- capture/logger.py exists and tested before any other script is written
- Every script has a test in tests/ before it is considered done
- All three processes (forwarder, safety_monitor, sqi_monitor) confirmed running simultaneously without interfering before Phase 3 is signed off
