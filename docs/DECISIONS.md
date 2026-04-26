# Consensai 1a — Decisions Log

Decisions made during Phase 0. Not to be relitigated without good reason.

## Dependency Management
- **Decision:** Poetry (pyproject.toml + poetry.lock)
- **Rationale:** Clean separation of production vs dev dependencies, automatic virtual environment management, deterministic installs via lockfile. requirements.txt was too flat and error-prone.
- **Date:** April 2026

## Version Control
- **Decision:** main is always clean and working. All development on feature branches. Merge only when task is complete and tested.
- **Branch naming:** feature/[task-name] (e.g. feature/lsl-forwarder)
- **Date:** April 2026

## Toolchain
- **Decision:** VS Code as editor with Continue extension, Qwen3.6 via Ollama locally (GPU-accelerated on RTX 4070), Claude Code CLI for agentic tasks, Claude.ai for planning and architecture.
- **Date:** April 2026

## Hardware — 1a Development Environment
- **Decision:** 1a development uses simulated LSL streams only. No real hardware in 1a.
- **Rationale:** Real device selection requires clinical partner confirmation. Building against simulated streams keeps 1a self-contained, reproducible, and hardware-agnostic. Any LSL-compatible device can be substituted in 1b without changing the pipeline.
- **What was deferred:** Device selection deferred until UCSF clinical partner confirms requirements.
- **What this means for code:** lsl_forwarder.py must work identically against simulated and real LSL streams. Stream names and sample rates come from config/settings.py — never hardcoded.
- **Date:** April 2026

## Compound-Specific Safety Thresholds
- **Decision:** Use published literature values as placeholders. All thresholds configurable via algorithm_params.yaml — never hardcoded.
- **Rationale:** Thresholds must be validated by a clinical expert. Placeholder values allow safety monitor to function during development without making clinical claims.
- **Who owns this permanently:** A qualified clinical collaborator. Must be revisited before any real participant data is collected.
- **Compounds and primary flags:** Ibogaine — R-R interval (most safety-critical). Psilocybin — heart rate, HRV. MDMA — heart rate. LSD — heart rate, HRV coherence.
- **What was rejected:** Hardcoding thresholds — unacceptable without expert sign-off.
- **Date:** April 2026

## WebSocket vs Polling
- **Decision:** WebSocket for all real-time delivery. No polling.
- **Rationale:** Safety alerts require lowest possible latency. WebSocket pushes events immediately. Polling introduces unacceptable delay for safety-critical alerts.
- **Implementation:** FastAPI native WebSocket. Endpoint: WS /sessions/{id}/stream. Delivers alert_events and SQI status in real time. Connection manager handles reconnect gracefully.
- **What was rejected:** HTTP polling — too slow for safety alerts.
- **Date:** April 2026

cat >> ~/consensai-1a/docs/DECISIONS.md << 'EOF'

## Logging Strategy
- **Decision:** JSON structured logging via shared logger at capture/logger.py. Every process imports it. Every log line includes: timestamp, process_name, log_level, session_id (nullable), message.
- **Log file structure:** One file per process per session. Path: logs/{session_id}/{process_name}.log
- **Retention:** Never auto-delete. Logs are part of the audit trail. Keep for duration of trial plus minimum 2 years.
- **Date:** April 2026

### Log Levels

**DEBUG**
- Raw sample counts per interval (throughput verification)
- Buffer writes and flushes (individual events during DB drop)
- Clock drift values (remote_clock_offset from LSL)

**INFO**
- Session start (session_id, participant_id pseudonymous, compound, compound_dose, compound_dose_unit, protocol_arm, site_id, sponsor_id)
- Session stop (session_id, duration, reason)
- Process start/stop (forwarder, safety_monitor, sqi_monitor)
- Device connect/disconnect (stream name, device ID, sample rate)
- Watermark verified (all streams passed, batch cleared)
- HUMeN manual inputs (coordinator_id, input_type, content, lsl_timestamp)
- Config snapshot at session start (full system config as JSONB to audit_events via trigger)
- Algorithm params loaded on every safety_monitor start/restart (exact thresholds from algorithm_params.yaml)
- Coordinator acknowledgment of safety alert (coordinator_id, alert_id, timestamp)

**WARNING**
- Buffer threshold exceeded (DB down longer than configurable threshold)
- SQI degradation (channel quality below acceptable threshold)
- Reconnection attempts (forwarder retrying DB connection)

**ERROR**
- DB write failure (write failed after retry, data buffering locally)
- LSL stream drop (device stream gone, not just momentary disconnect)
- XDF write failure (backup reconciliation source failed to write)

**CRITICAL**
- Safety alert fired (algorithm_name, algorithm_version, threshold breached, measured value)
- Watchdog restart (forwarder crashed, systemd restarted it)
- Watermark failed (stream gap detected, batch blocked, coordinator alerted)

### Key Decisions
- Algorithm params logged on every safety_monitor process start, not just session start. Covers watchdog restart scenarios where thresholds could theoretically change.
- File locking of algorithm_params.yaml during sessions deferred to 1b. Logging is sufficient for 1a.
- Config snapshot is one JSONB payload to audit_events at session start. Proves exact system state during any given session.
- compound_dose and compound_dose_unit added to sessions table. Dose units vary by compound (grams for psilocybin, micrograms for LSD, milligrams for MDMA, mg/kg for ibogaine).
EOF

