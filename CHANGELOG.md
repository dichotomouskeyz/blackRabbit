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

## [0.3.0] - 2026-10-13

Operator console release and repository cleanup.

### Added

- Agent-first operator console in `web/` (Next.js 15): a sessions and
  capability rail, a chat that drives the operator API through a local
  OpenAI-compatible model with tool calling, tool cards backed by API
  responses, and a manual create form that works without the model.
- Server-side agent route that allows only loopback or private egress, bounds
  each turn with a timeout, caps tool calls at the real dispatch, fences tool
  output as untrusted data, and corrects success claims that a refused tool
  contradicts.
- Typed API client and a closed ten-tool registry whose endpoints are checked
  against the routes in `api/app.py`.
- Frontend test gate: Vitest and Testing Library suites plus a production build
  scanned for server-only `AGENT_*` values.
- Design mockups for the console in `docs/ui-mockups/`.

### Changed

- The README describes the console, and the agent context files point at the
  current release documents.

### Removed

- Simulated XDF recordings are no longer tracked.
- The root `package.json` for an unrelated tool, empty scaffolds (`src/`,
  `storage/`, `models.config`, `db/SCHEMA.md`, `docs/migration_1a_to_1b.md`),
  Poetry-era editor settings, the retired `tests/_archive` suite, and agent
  prompts and the phase 0 decision log written under a retired project name.
- Private partner names in comments and historical documents.

## [0.2.0] - 2026-10-13

Backend release. Each entry below landed as its own commit.

### Added

- Capture writes standard XDF 1.0 files with a durable flush before each
  matching database write; independent `pyxdf` parsing is part of the tests.
- Canonical session ownership: capture, recovery and closeout serialize on a
  shared advisory lock and refuse a mismatched session identity.
- Reconciliation validates tenant-scoped XDF files, replays missing samples and
  checks complete EEG channels before closeout sets the database watermark.
- ARC analysis: shared feature extraction, versioned baselines, successive
  response windows, seeded circular-shift null tests, Benjamini-Hochberg FDR
  and reproducible JSON artifacts through `python -m batch.arc`.
- The operator API serves tenant-scoped ARC reports through a read-only
  database role.
- Recording investigation agent (optional `agent` extra) with six typed,
  read-only tools, cited findings and a headless synthetic demonstration.
- Smoke scripts for an isolated backend demonstration and a real LSL process
  check.
- A backend CI workflow that provisions database roles and verifies the
  release against an isolated database.
- Analysis provenance and composite profile columns in their owning migrations.

### Changed

- A failed required capture worker stops capture. Automatic restart is
  disabled until segmented resume can preserve sample identity.
- Capture closeout no longer starts ARC; analysis runs as an explicit step.
- Python lint and tests ignore the `web/` tree, and `ANTHROPIC_API_KEY` was
  removed from the settings.
- Package metadata and an sdist allowlist for the backend release.

### Fixed

- The 0.1.0 known issue: the README now describes code that is in the release.

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

[Unreleased]: https://github.com/dichotomouskeyz/blackRabbit/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/dichotomouskeyz/blackRabbit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dichotomouskeyz/blackRabbit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dichotomouskeyz/blackRabbit/releases/tag/v0.1.0
