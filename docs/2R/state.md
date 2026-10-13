# Branch 2R State

**Branch:** `2R`
**As of:** 2026-06-11
**Scope:** Phase 2 capture, reconciliation, schema, ARC tenancy, and test-contract work
**Canonical open work:** [backlog.md](backlog.md)
**Database deep dive:** [db-health.md](db-health.md)
**Historical source material:** [`docs/_archive/phase-2-reviews/`](../_archive/phase-2-reviews/)

## Executive Summary

Branch 2R has completed the structural Phase 2 refactors it set out to do:

- `StreamThread` owns its connection, inlet, logger, and mutable
  `StreamThreadState`;
- forwarder startup and shutdown are organized through `ForwarderEngine`;
- forwarder preflight shares one connection and uses typed failures;
- session metadata construction uses `SignalMetadataRow`;
- session initialization validates inputs before opening the DB and writes a
  schema-version record;
- selected ARC entry points accept sponsor scope;
- reconciliation signatures and tenancy guards are aligned with the specs;
- the database was rebuilt from the canonical migration chain ending at 030.

The capture package is structurally sound and does not need a broad rewrite.
Remaining capture risk is concentrated in lifecycle and durability boundaries:
ARC ordering, required-stream failure propagation, XDF failure visibility,
canonical identity validation, durable terminal state transitions, and the
remaining user-gated test harness work.

The branch is suitable for moving toward the next phase after one focused
capture stabilization pass. Lower-risk database operations and deployment work
remain tracked in [backlog.md](backlog.md).

## Current Architecture

### Capture

- Session initialization, APEX forwarding, ECHO handling, XDF writing,
  watchdog supervision, and session close remain separate packages.
- APEX data remains split across EEG, HRV, EDA, and respiration tables.
- `lsl_timestamp` and `db_insert_time` remain distinct.
- XDF is invoked before the DB write path.
- DB outages use bounded per-thread buffers and reconnect/flush behavior.
- Session close compares XDF and DB counts and backfills positive gaps.
- Structured JSON logging and pseudonymous UUID identity are preserved.

### Phase 2 Ownership Patterns

- `StreamThread` owns `conn`, `inlet`, and `StreamThreadState`.
- Stream helper functions receive the owning thread rather than passing the
  connection through every call.
- `ForwarderEngine` exposes `prepare`, `start`, `run_until_stopped`, and
  `stop` phases while `run_forwarder` remains the CLI wrapper.
- `SignalMetadataRow` mirrors the metadata insert shape and replaces the
  former null-dictionary shadow schema.
- `run_preflight` performs session checks and configuration loading over one
  connection.

### Database and Tenancy

- Alembic is the schema source of truth; the active chain is 001 through 030.
- `capture_source` / `CAPTURE_SOURCE` is the canonical simulated-vs-hardware
  name.
- ARC session reads accept and apply `sponsor_id`.
- Session-close updates can apply a sponsor guard.
- Sample and integrity writes now share the same transaction, including the
  buffer-flush path.

## Phase-Exit Findings

### CAP-01 - ARC Runs Before `watermark_verified`

**Status:** Open, high priority.

Session close still reconciles, runs `run_arc_post_session`, and only then
closes the session. ARC can therefore begin before the verified watermark and
capture completion remains coupled to unfinished ARC behavior.

**Exit condition:** close and watermark the reconciled capture first. ARC must
start from a separate batch entry point that requires `watermark_verified`.

### CAP-02 - Required Stream Failure Can Be Invisible

**Status:** Partially improved, still open.

`StreamThreadState`, shared stop propagation for fatal `RuntimeError`, and
`ForwarderEngine` are complete. However, missing required inlets or initial DB
connections still return from a thread without marking the forwarder fatal,
and unexpected exception classes can still terminate only one stream thread.

**Exit condition:** every required APEX stream startup/runtime failure must set
the shared stop event, retain the fatal error, and produce a nonzero forwarder
exit.

### CAP-03 - XDF Failure Does Not Stop the DB Path

**Status:** Open, high priority.

XDF write errors are logged and swallowed while the corresponding DB write can
continue. Sample/timestamp cardinality is also encoded without an equality
check.

**Exit condition:** validate XDF payload shape before encoding and propagate
write/finalization failure before the same record is committed to the DB.

### CAP-04 - Canonical Session Identity Is Not Fully Enforced

**Status:** Partially improved, still open.

Sponsor scoping is substantially stronger across ARC and session-close paths.
Forwarder preflight still retains caller-provided participant and site IDs
instead of loading or comparing them with the canonical session row.
Reconciliation helper reads also retain some session-ID-only queries.

**Exit condition:** load canonical identity or require exact identity matches,
and consistently carry sponsor scope through session reads.

### CAP-05 - Terminal Lifecycle Persistence Is Not Guaranteed

**Status:** Open, medium priority.

Unexpected reconciliation failure can leave a session in `closing`. Watchdog
terminal-state helpers log and swallow DB failures, so the process can exit
without a queryable failed state.

**Exit condition:** terminal state writes must expose success/failure and
unexpected close failures must produce a durable failed outcome where the DB
is reachable.

### CAP-06 - Critical Test Harness Work Remains

**Status:** Partially resolved.

The Phase 2 implementation work reduced the historical full-suite failures
from 46 to 10. Four forwarder chunk/drift tests became green after the
StreamThread refactor. The remaining ten failures require user-gated test
fixture changes:

- 5 ECHO tests construct buffer-only `ECHOWriter` with an unrelated config;
- 4 ARC tests use a placeholder config object rather than the real config
  contract;
- 1 session-close test builds but never installs its tracking wrapper.

Four watchdog-loop tests also remain explicit placeholders and skip.

**Exit condition:** correct the ten stale test fixtures, replace the watchdog
loop placeholders, and run one simulated end-to-end capture-close workflow.

## Completed Phase 2 Work

- [x] Rebuild the database from clean migrations 001 through 030.
- [x] Remove the abandoned capture-mode repair revisions.
- [x] Validate session-init compound, participant UUID, and dose unit before
      opening the DB.
- [x] Persist `schema_version_log` during session initialization.
- [x] Replace the metadata null-dictionary schema with `SignalMetadataRow`.
- [x] Scope ARC reads by sponsor.
- [x] Align reconciliation argument order, path handling, and return shapes.
- [x] Add sponsor guarding to session-close updates.
- [x] Make watchdog restart-event logging non-fatal and close its DB
      connection on all established-connection paths.
- [x] Make `StreamThread` own connection, inlet, and mutable state.
- [x] Rework stream DB helpers around thread-owned resources.
- [x] Keep sample and integrity writes in one transaction.
- [x] Include integrity writes during buffer replay.
- [x] Add shared-connection forwarder preflight and typed preflight failures.
- [x] Add `ForwarderEngine` lifecycle phases.
- [x] Correct the migration, architecture, and Correctless documentation.
- [x] Verify `SCHEMA.md` against the canonical capture migrations.

## Capture Exit Checklist

- [ ] Decouple ARC execution from capture session close.
- [ ] Require `watermark_verified` before every ARC batch entry point.
- [ ] Make missing required inlets and unexpected stream exceptions fatal.
- [ ] Validate XDF sample/timestamp cardinality and channel shape.
- [ ] Propagate XDF write and finalization failures.
- [ ] Load or strictly verify canonical participant/site/sponsor identity.
- [ ] Make reconciliation exceptions produce a queryable terminal outcome.
- [ ] Make watchdog terminal-state persistence observable.
- [ ] Replace the four watchdog-loop placeholder tests.
- [~] Repair the integration harness: 36 historical failures resolved; 10
      user-gated fixture failures remain.
- [ ] Run an end-to-end simulated session through initialization, APEX/ECHO
      capture, watchdog shutdown, XDF close, reconciliation, and watermarking.

## Accepted MVP Risks

These do not block the next phase unless product requirements change:

- bounded DB buffers may discard the oldest chunks because XDF is the
  reconciliation source;
- permanent DB constraint failures may drop a DB chunk while preserving XDF;
- ECHO may be absent without stopping APEX biosignal capture;
- ECHO buffer overflow may discard old contextual events;
- XDF stores biosignal values as float32 while the DB stores higher precision;
- import-time settings validation is inconvenient for some tooling;
- broad class-based rewrites, generic sink abstractions, and a StreamFactory
  are unnecessary until a real new modality or consumer requires them;
- `SessionRequest` and `SessionRepository` remain deferred until the UI/API
  boundary exists.

An XDF loss, invisible required-stream failure, identity mismatch, or false
terminal state is not an accepted buffering risk and remains in the exit
checklist.

## Verification Snapshot

Current full-suite run on 2026-06-11:

```text
10 failed, 297 passed, 4 skipped
```

- The ten failures are the user-gated fixtures listed under CAP-06.
- The four skips are watchdog-loop placeholders.
- The non-integration gate on 2026-06-11 passed:
  `245 passed, 4 skipped, 62 deselected`.
- `uv run ruff check capture batch config` passed.
- `uv run pyright capture` reported three errors and one warning:
  the ECHO DB return type, generic-thread access to `fatal_error`, optional
  Alembic head, and `capture.__all__`.

Historical baseline and rerun details are archived under
[`test_suite_regen/`](../_archive/phase-2-reviews/test_suite_regen/).

## Readiness Verdict

**State:** Phase 2 is incomplete. Its planned structural refactors are present,
but focused capture stabilization is still required.

The branch has completed the refactors that reduce coupling and clarify
ownership. It should not undergo another broad capture rewrite. Complete the
six phase-exit findings, then move forward and treat the remaining operational,
deployment, and optional design work as backlog.
