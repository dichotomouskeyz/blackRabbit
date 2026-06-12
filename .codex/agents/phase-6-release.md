# Phase 6 Release Playbook

Use this playbook for hardening and open-source release prep. This is a release
checklist, not a feature-build phase — there is no registered phase-6 agent.

## Goal

Make the repo safe and reproducible to release (MIT, local research tool):
security pass, data-integrity validation, and a cold-start quickstart that works
for someone who is not the author.

## Gate Criteria

Salvaged from the retired Notion "testing strategy phase x phase" page and
translated to current naming.

Security / hygiene:
- No real credentials anywhere in the repo — confirmed via grep and git-log scan.
- `.env` is gitignored and has never been committed.
- No real participant identity in any table — pseudonymous IDs only.
- No dead private context in the public repo (no "Untitled Biometric Platform",
  "Neurobiometric", "Consensai", or "UCSF" references).
- Pre-commit hooks active and blocking sensitive files.

Data integrity:
- Audit-trail replay over a complete session is complete, ordered, and
  tamper-evident; no application path writes `audit_events` directly.
- `lsl_timestamp` and `db_insert_time` are never equal on any row across a full
  session.
- XDF↔DB reconciliation result is persisted on every session close.
- The integrity log has one entry per chunk write across all four biosignal
  hypertables.

End-to-end:
- The quickstart flow works on a clean machine with no hidden dependencies, run
  by someone other than the author.
- A full simulated session runs the complete batch chain without errors.

## Do Not Build

- New features. Phase 6 is hardening and proof, not scope expansion.
