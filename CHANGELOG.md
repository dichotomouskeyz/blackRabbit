# Changelog

All notable changes to blackRabbit are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Versions stay at
0.x while the platform is an unvalidated research tool.

"1a" and "1b" are roadmap milestones, not version numbers: 1a is the local,
post-session research tool and 1b is the cloud, real-time, compliance-ready
deployment. The database schema (Alembic revisions) and the capture payload
schema (`PAYLOAD_SCHEMA_VERSION`) carry their own version numbers, separate
from the product version.

## [Unreleased]

Work in progress on a local machine, not yet pushed. The README on `main`
already describes some of it.

## [0.1.0] - 2026-10-13

First tagged release. It packages the 1a code last updated on 2026-06-12
(previously on `feature/phase-4-ui`) and merges it into `main`.

### Added

- Database: TimescaleDB and pgvector schema through Alembic migrations
  001 to 030, plus optional governance migrations (consent, electronic
  signatures, investigational product and adverse event logs), including hypertables for EEG, HRV (R-R intervals), EDA and
  respiration, pseudonymous sessions, an append-only audit trail with
  insert triggers, ECHO event and alert tables, compound reference data,
  EEG electrode metadata, a biosignal integrity log, session baselines,
  Event Composite Profile storage and a schema version log.
- Capture: LSL forwarder with per-modality stream threads that commit
  sample chunks and integrity logs atomically, session initialization with
  pre-flight validation, ECHO marker handling with write retry, session
  close, a process watchdog with audit logging and systemd units, and a synthetic board for
  simulated sessions.
- Recovery: XDF writer, XDF and database reconciliation, and missing-sample
  backfill.
- Batch: per-modality batch processing for EEG, HRV, EDA and respiration,
  and the first ARC stage: echo anchor clustering, session baselines and
  W1/W2/W3 response windows with temporal alignment checks.
- Operator API (M0): capability-gated FastAPI service for sessions, ARC
  results, frames and a WebSocket tap, with tenancy checks.
- Tooling: simulation runner, detect-secrets baseline and pre-commit hooks, and a test suite.

### Changed

- Dependency management moved from Poetry to uv; `poetry.lock` was removed.
- The Phase 0 decisions log moved to `docs/decisions-phase-0.md` so it no
  longer collides with `docs/decisions.md` on case-insensitive filesystems.

### Known issues

- The README describes features that are not in this release: the
  circular-shift null tests with Benjamini-Hochberg FDR, the PydanticAI
  recording investigator, and the `scripts.backend_smoke` and
  `scripts.investigation_smoke` demonstrations.
- The package and database names still use the placeholder
  `untitledplatform_1a`.

[Unreleased]: https://github.com/dichotomouskeyz/blackRabbit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dichotomouskeyz/blackRabbit/releases/tag/v0.1.0
