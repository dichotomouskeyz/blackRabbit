# Capture Package State - Phase 2

**Audit date:** 2026-06-11
**Snapshot:** Point-in-time Phase 2 capture assessment as of 2026-06-11
**Scope:** `capture/`, capture-facing reconciliation, and capture lifecycle tests
**Purpose:** Record the state of the capture package before moving into the next MVP phase
**Implementation changes made by this audit:** None

## Executive Summary

The capture package is structurally sound and does not need a broad refactor.
Its modules have reasonably clear ownership boundaries, production code passes
Ruff, and the non-integration suite has broad happy-path coverage.

Capture should not be considered fully phase-complete yet. The remaining work
is a narrow stabilization pass around lifecycle and durability boundaries:

1. ARC must not run from session close before `watermark_verified`.
2. Required stream failures must stop the forwarder instead of silently
   degrading capture.
3. XDF write and payload-validation failures must be visible to the forwarder
   before the corresponding DB write proceeds.
4. Forwarder identity must be loaded from, or strictly verified against, the
   canonical session row.
5. Terminal session-state persistence and watchdog-loop behavior need focused
   tests.

After those items are addressed, moving on from capture is reasonable. The
package does not need to be perfect before the next phase, and the remaining
lower-risk cleanup can stay in the backlog.

## What Is Already in Good Shape

- Capture remains split into focused subsystems: session initialization,
  forwarder, ECHO handling, XDF writing, watchdog supervision, and session
  close.
- APEX biosignal rows preserve separate EEG, HRV, EDA, and respiration tables.
- `lsl_timestamp` and `db_insert_time` remain separate.
- XDF is invoked before the DB write path for APEX and ECHO records.
- DB outages have bounded in-memory buffering and reconnect/flush behavior.
- XDF-to-DB reconciliation and positive-gap backfill exist.
- Session lifecycle transitions and watermark triggers exist.
- Runtime configuration is sourced through `config/settings.py`.
- SQL values are parameterized, and dynamic table names use closed mappings.
- Structured JSON logging and pseudonymous identifiers are preserved.
- Production capture code passes Ruff.

## Phase-Exit Findings

### 1. High - ARC Runs Before the Verified Watermark

`capture/session_close/workflow.py` currently:

1. reconciles the session;
2. runs `run_arc_post_session`;
3. calls `close_session`, which emits `watermark_verified` or
   `watermark_failed`.

This ordering allows ARC to start before the database has emitted
`watermark_verified`. It also keeps capture completion dependent on the
unfinished ARC implementation.

**Required direction:** session close should reconcile and establish the
terminal capture state. ARC should be triggered separately and only after a
closed, watermark-verified session is observable.

**Evidence:** `capture/session_close/workflow.py:97`, `:120`, and `:155`.

### 2. High - Required Stream Threads Can Exit Without Failing the Forwarder

`capture/forwarder/stream_thread/stream_runtime.py` logs and returns when an
LSL inlet or initial DB connection cannot be established. The thread wrapper
only promotes `RuntimeError` to `fatal_error`.

Consequences:

- one required modality can disappear while the process remains alive;
- malformed samples can raise `ValueError` or `IndexError` and terminate only
  one thread;
- the watchdog sees a healthy forwarder process and does not restart it.

**Required direction:** failure to start or continue a required APEX stream
must set the shared stop event, record the fatal error, and cause a nonzero
forwarder exit.

**Evidence:** `capture/forwarder/stream_thread/stream_runtime.py:13`, `:18`,
and `:64`.

### 3. High - XDF Failures Are Logged but the DB Path Continues

`XDFWriter.write_samples` and `write_marker` catch `OSError`, log it, and
return. `process_chunk` then continues building and inserting DB rows.

This behavior is currently documented as an accepted Correctless MVP risk,
but it weakens the architectural claim that XDF is the capture continuity
source. A disk-full event can produce DB records that have no XDF equivalent,
and reconciliation cannot reconstruct the missing XDF records.

There is also no cardinality validation before encoding. The payload records
`len(timestamps)` but writes records using `zip(timestamps, samples)`.
Different lengths can therefore produce an internally inconsistent XDF chunk.

**Required direction:** validate sample/timestamp cardinality and channel
widths at the XDF boundary. Once XDF becomes unavailable, propagate a fatal
capture state before writing the same chunk to the DB.

**Evidence:** `capture/xdf/writer.py:124`, `:161`;
`capture/xdf/samples.py:31-32`; and
`capture/forwarder/stream_thread/stream_chunks.py:11-12`.

### 4. High - Caller-Supplied Identity Is Not Fully Verified

Forwarder preflight verifies `(session_id, sponsor_id)` and required metadata,
but it retains the caller-provided `participant_id` and `site_id`.
Those values are then copied into XDF headers and every biosignal row.

The biosignal table schemas require the identity columns but do not enforce
that they match the canonical `sessions` row. A valid session ID paired with
the wrong participant or site UUID can therefore create inconsistent
provenance.

**Required direction:** load participant, site, and sponsor identity from the
session row, or fail preflight unless every supplied value exactly matches it.

**Evidence:** `capture/forwarder/preflight.py:19` and `:87-89`;
`capture/forwarder/rows.py`.

### 5. Medium - Terminal Lifecycle Persistence Is Not Guaranteed

An unexpected exception during reconciliation can leave a session in
`closing` without either watermark. Separately, after maximum forwarder
restarts, the watchdog exits even if `mark_session_failed` could not persist
the failed state.

The logging is useful, but logs do not replace the queryable terminal state
used by downstream gates.

**Required direction:** make terminal-state writes explicit success/failure
operations. Session close must convert unexpected reconciliation failures
into a durable `failed` state where possible. The watchdog must not report a
completed failure transition when the update did not occur.

**Evidence:** `capture/session_close/workflow.py:97`;
`capture/watchdog/runner.py:137-138`; and
`capture/watchdog/db.py:126-150`.

### 6. Medium - Critical Supervision Tests Are Not Active

The four watchdog-loop contract tests are explicit placeholders and always
skip. They do not currently prove restart accounting, clean shutdown,
maximum-restart failure, or restart-event logging.

The regenerated integration suite also contains interface drift. Examples
include constructing `ECHOWriter` with a config it does not own, calling old
reconciliation argument orders, and passing strings where the production CLI
already supplies `Path`.

Tests should be corrected to exercise the intended production interfaces.
That does not mean changing correct implementation behavior merely to satisfy
stale test assumptions.

**Evidence:** `tests/capture_tests/watchdog/test_loop.py:64-73`.

## Verification Snapshot

### Production checks

- `uv run ruff check capture`: passed.
- `uv run pyright capture`: two errors and one warning.
  - `capture/echo_handler/writer.py:42`: inferred optional return from the DB
    helper is treated as non-iterable.
  - `capture/session_init/workflow.py:24`: Alembic head may be `None` but the
    function declares `str`.
  - `capture/__init__.py:3`: `forwarder` appears in `__all__` without being
    imported into the module.

These type-checking findings are cleanup items rather than evidence of a broad
architectural problem.

### Non-integration tests

- 245 passed.
- 4 skipped.
- 62 integration tests were deselected in that run.
- The four skips are the unwired watchdog-loop tests.
- Non-integration capture coverage was approximately 49.5%.

Coverage is strongest around XDF writing and narrower helpers. Important
runtime orchestration paths in the forwarder, ECHO runtime, session close, and
watchdog remain lightly covered.

### Live integration run

The integration database was available during the audit:

- 27 tests passed.
- 35 tests failed.
- 249 tests were deselected by the integration marker selection.

Subsystem results included:

| Subsystem | Result | Audit interpretation |
|---|---:|---|
| Session initialization | 7 passed | Integration path is in comparatively good shape. |
| Watchdog DB behavior | 5 passed | DB helpers work against the live schema; loop behavior is still skipped elsewhere. |
| ECHO handler | 5 failed | Regenerated tests use stale constructor/runtime interfaces. |
| Forwarder | 4 failed | Tests reference moved constants and outdated helper signatures. |
| Reconciliation | 6 passed, 8 failed | Several failures are argument-order and return-shape drift; tenancy hardening remains valid debt. |
| Session close | 13 failed | Tests pass `str` directly while the production CLI supplies `Path`; ARC coupling remains a real design issue. |

The raw failure count should not be interpreted as 35 production bugs.
However, a failing integration suite cannot serve as a phase-exit gate until
the stale harness contracts are corrected.

## Accepted Phase-2 Risks

The following do not need to block movement into the next phase once the
phase-exit findings above are resolved:

- bounded DB buffers can overflow and discard the oldest chunks because XDF
  remains the reconciliation source;
- non-operational DB constraint failures can drop a DB chunk while preserving
  the XDF record;
- ECHO may be absent without stopping APEX biosignal capture;
- ECHO buffer overflow can discard old contextual events;
- XDF stores biosignal values as float32 while the DB stores greater
  precision;
- session-close and reconciliation helper APIs could be cleaner;
- import-time settings validation is inconvenient for tooling;
- the two Pyright errors and `__all__` warning are small cleanup items;
- broader class-based refactors are unnecessary.

The important distinction is that an accepted DB loss is recoverable from
XDF. An XDF loss, invisible required-stream failure, false terminal state, or
identity mismatch is not equivalent and should not be treated as ordinary
buffering debt.

## Recommended Phase-2 Exit Checklist

- [ ] Remove ARC execution from the capture session-close transaction.
- [ ] Require `watermark_verified` before any ARC batch entry point can run.
- [ ] Promote missing required inlets and unexpected stream exceptions to a
      fatal forwarder exit.
- [ ] Validate sample/timestamp cardinality before XDF encoding.
- [ ] Propagate XDF write and finalization failures to the forwarder and
      watchdog.
- [ ] Load or strictly verify canonical participant/site/sponsor identity
      during forwarder preflight.
- [ ] Ensure reconciliation exceptions produce a queryable failed outcome.
- [ ] Make watchdog terminal-state write success observable.
- [ ] Replace the four watchdog-loop skips with real unit tests.
- [ ] Repair the capture integration harness so it calls current production
      interfaces.
- [ ] Run one end-to-end simulated session through init, APEX/ECHO capture,
      watchdog shutdown, XDF close, reconciliation, and watermark verification.

## Phase Readiness Verdict

**State:** nearly complete, with a focused stabilization pass required.

The capture package is not bug-free, but it is also not broadly brittle. Its
remaining risk is concentrated in lifecycle boundaries rather than in the
overall module structure. A broad rewrite or class-oriented refactor would add
risk without solving the important problems.

Complete the exit checklist's durability, failure-propagation, identity, and
watermark items, then move into the next phase. Lower-priority cleanup can be
handled when capture is revisited through a real failing workflow or a focused
maintenance pass.
