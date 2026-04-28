## Hardware — 1a Development Environment
- **Decision:** 1a development uses simulated LSL streams only. No real hardware in 1a.
- **Rationale:** Real device selection requires clinical partner confirmation. Building against simulated streams keeps 1a self-contained, reproducible, and hardware-agnostic. Any LSL-compatible device can be substituted in 1b without changing the pipeline.
- **What was deferred:** Device selection (EEG headset brand/model, HRV sensor, EDA sensor, respiration belt). Deferred until UCSF clinical partner confirms requirements.
- **What this means for code:** lsl_forwarder.py must work identically against simulated and real LSL streams. Stream names and sample rates come from config/settings.py — never hardcoded.
- **Date:** April 2026

## Compound-Specific Safety Thresholds
- **Decision:** Use published literature values as placeholders for all compound-specific safety thresholds. All thresholds are configurable via algorithm_params.yaml — never hardcoded.
- **Rationale:** Thresholds must eventually be validated by a clinical expert with compound-specific knowledge. Placeholder values from literature allow the safety monitor to function during development without making clinical claims.
- **Who owns this decision permanently:** The clinical collaborator — a qualified medical professional with psychedelic research experience. This decision must be revisited and signed off before any real participant data is collected.
- **Compounds and primary safety flags:**
  - Ibogaine — R-R interval monitoring (cardiac). Highest sensitivity threshold. Most safety-critical.
  - Psilocybin — heart rate, blood pressure proxy via HRV
  - MDMA — heart rate, body temperature proxy
  - LSD — heart rate, HRV coherence
- **What was rejected:** Hardcoding thresholds. Unacceptable — clinical decisions cannot be embedded in code without explicit expert sign-off.
- **Date:** April 2026

## WebSocket vs Polling for Real-Time Delivery
- **Decision:** WebSocket for all real-time delivery to the coordinator interface. No polling.
- **Rationale:** Safety alerts require the lowest possible latency — a coordinator must see a cardiac anomaly the moment it fires, not on the next poll interval. WebSocket maintains a persistent connection and pushes events immediately. Polling introduces artificial delay that is unacceptable for safety-critical alerts.
- **Implementation:** FastAPI native WebSocket support. Endpoint: WS /sessions/{id}/stream. Delivers both alert_events and SQI status in real time. Connection manager handles reconnect gracefully — if the coordinator closes the browser mid-session, the WebSocket reconnects on reload without losing session state.
- **What was rejected:** HTTP polling. Too slow for safety alerts. Adds complexity without benefit given FastAPI's native WebSocket support.
- **Date:** April 2026
