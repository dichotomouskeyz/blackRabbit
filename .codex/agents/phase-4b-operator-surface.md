# Phase 4b Operator Surface Playbook

Use this playbook for thin local researcher/operator workflows.

## Goal

Expose capture, closeout, baseline, ARC review, and export workflows through
scriptable local interfaces without committing to a broad web app.

## Build Rules

- Prefer CLI and notebook-friendly interfaces.
- Wrap existing capture and batch modules.
- Keep output reproducible and safe to regenerate.
- Avoid real participant identity in exported artifacts.
- Keep language research-tool oriented.

## Do Not Build

- broad FastAPI backend
- React coordinator UI
- live WebSocket dashboards
- cloud deployment
- duplicate business logic copied from capture or batch modules

## Verification

Run tests for command help, argument validation, missing-session behavior, output
shape, and validation gates.

## Gate Criteria

Salvaged from the retired Notion "testing strategy phase x phase" page and
translated to current naming.

- An `analyze --session <id>` workflow triggers the full batch chain and outputs
  the ARC interpretation.
- A `sessions` workflow lists sessions; a `status --session <id>` workflow shows
  session state, sample counts, and safety alerts.
- The surface installs/runs via `uv` from a clean clone and works against a fresh
  simulated session with no manual steps beyond the quickstart.
- (Optional, deferred) A thin read-only endpoint returns ECPs + interpretation as
  JSON — only if the UI work is reintroduced; see `docs/ui-integration.md`.
- Exported artifacts never contain real participant identity.
