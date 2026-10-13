# Phase 5b ARC Batch Playbook

Use this playbook for Agentic Response Convergence batch tasks.

## Goal

Process complete post-session ECHO/APEX records into deterministic convergence
artifacts and optional agentic interpretation over those artifacts.

## Build Rules

- Keep imports under `batch.arc.*`.
- Run after session close and validation.
- Treat raw APEX/ECHO rows as immutable inputs.
- Compute W1/W2/W3 window responses from stored timestamps.
- Use persisted baselines when comparing observed response values.
- Record config and algorithm provenance on generated artifacts.
- Represent missing signals explicitly.

## Do Not Build

- live convergence during capture
- raw data mutation
- broad UI/API surfaces
- replacement reconciliation paths

## Verification

Run tests for import stability, anchor filtering, window boundaries, missing
signal behavior, deterministic convergence outputs, and session-close ARC
handoff.

## Gate Criteria

Salvaged from the retired Notion "testing strategy phase x phase" page and
translated to current naming. These are what Phase 5b must prove before Phase 4b.
Components not yet built are marked (TODO).

- `batch/arc/processor.py` produces ECPs for a simulated session with multiple
  ECHO events; `arc_config_version` is populated on every ECP row.
- (TODO) Convergence math lives in isolated pure functions (deviation score,
  participation decision, convergence density, null distribution with a fixed
  seed, Benjamini-Hochberg FDR matching scipy) in a `batch/arc/convergence`
  module; the processor calls only those — no inline reimplementation.
- Null distribution produces meaningful p-values and the FDR filter removes
  noise events.
- The processor reads `sqi_flag` and excludes degraded windows (>50% flagged,
  configurable), and fails loud if `session_baselines` is empty for the session.
- `arc_batch_complete` is written to `audit_events` on completion.
- (TODO) `batch/arc` interpreter reads only FDR-passed ECPs, never recomputes
  convergence, cites `echo_event_id` + the metric for every claim, and includes
  a safety summary when `safety` alerts exist; writes
  `arc_interpretation_complete` to `audit_events`.
- Integration: full chain baseline → SQI → safety → ARC → interpreter; run twice,
  ECP output identical both times (narrative wording may vary, cited facts may
  not).
- Performance: full chain completes well within a session-length budget; null
  distribution (1000 shuffles) is reasonable for ~50 ECHO events.
- DB-backed gates use `@pytest.mark.integration` + `TEST_DATABASE_URL`.
