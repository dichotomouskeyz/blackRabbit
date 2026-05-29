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
