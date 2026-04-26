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
