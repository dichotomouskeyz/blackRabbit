# Decisions

## Hardware - 1a Development Environment

- **Decision:** 1a development uses simulated LSL streams by default.
- **Rationale:** Simulated streams keep the MVP self-contained, reproducible,
  and hardware-agnostic. Any LSL-compatible device can be substituted later if a
  research deployment needs it.
- **Deferred:** Device selection for EEG, HRV, EDA, and respiration.
- **Code impact:** Capture commands must work the same way against simulated
  and real LSL streams. Stream names and sample rates come from
  `config/settings.py`.
- **Date:** April 2026

## Safety Thresholds

- **Decision:** Live safety-monitor semantics are deferred from the research MVP.
- **Rationale:** Thresholds that imply participant intervention need domain
  validation and should not be presented as product behavior in the local MVP.
- **Current behavior:** Placeholder safety modules may exist, but the active
  Phase 2 path is capture, XDF backup, reconciliation, and post-session
  analysis.
- **Code impact:** Do not hardcode safety thresholds into capture code. Any
  future monitor must be configuration-driven and explicitly scoped.
- **Date:** April 2026; reframed May 2026

## Real-Time Delivery

- **Decision:** Broad real-time delivery and coordinator UI work are deferred.
- **Rationale:** The current path is local capture plus post-session ARC
  processing. A larger API/UI surface would add maintenance cost before the
  batch contracts are stable.
- **Deferred:** Broad FastAPI service, WebSocket event stream, and React
  coordinator UI.
- **Code impact:** Keep capture and batch interfaces CLI-friendly and
  replayable. If an API is introduced later, it should wrap existing contracts
  instead of replacing them.
- **Date:** April 2026; reframed May 2026

## Local Model Agent Neutrality

- **Decision:** The repo does not hardwire a local-model coding agent.
- **Rationale:** Local model work may use LM Studio, LiteLLM, Continue, Claude
  Code, Codex, or another coding agent while the workflow is still being tested.
- **Current behavior:** Repo docs only record the common local endpoint shape:
  LM Studio serving an OpenAI-compatible API at `http://localhost:1234/v1`.
- **Code impact:** Keep model/provider config out of application code. User-level
  files such as `C:\Users\jahlo\.continue\config.yaml` and
  `C:\Users\jahlo\.claude\litellm\config.yaml` stay outside repo ownership.
- **Date:** June 2026
