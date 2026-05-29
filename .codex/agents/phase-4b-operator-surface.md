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
