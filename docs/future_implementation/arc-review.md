# ARC Review

## Status

Deferred for a dedicated ARC review session. This document records the current
review findings and provides a starting order for investigation. It does not
approve the current ARC behavior for production or research use.

## Priority Findings

### 1. ARC Runs Before Watermark Verification

The session-close workflow currently invokes ARC before `close_session` writes
`watermark_verified`. ARC can also run after reconciliation reports gaps, then
persist baselines before the session is marked `failed`.

Review goal:

- run ARC only after reconciliation succeeds;
- require a closed, watermark-verified session before ARC batch work starts;
- ensure unreconciled sessions never generate ARC artifacts.

### 2. Temporal Preflight Is Not Connected

`batch.arc.preflight.assert_arc_temporal_alignment` exists, but
`run_arc_post_session` does not call it. ARC therefore computes baselines without
enforcing the documented ECHO/APEX timestamp-alignment gate.

Review goal:

- make temporal preflight a mandatory ARC entry gate;
- pass config-selected anchor filters and sponsor tenancy into the gate;
- surface a useful failure report without producing partial ARC output.

### 3. Failed ARC Transactions May Leave Sessions Closing

ARC database failures are wrapped as `ARCPostSessionError`, but the active
transaction is not rolled back first. PostgreSQL may leave the connection in an
aborted transaction state, causing the subsequent attempt to mark the session
`failed` to fail as well.

Review goal:

- define transaction ownership for reconciliation, ARC, and session status;
- roll back failed ARC work before updating terminal session state;
- verify no partial baseline writes remain after ARC failure;
- ensure the session always reaches a terminal status.

### 4. Baseline Labels and Calculations Do Not Reliably Match

Several configured signal-component names currently map to proxy or unrelated
calculations:

- EEG alpha, theta, and beta power all use average absolute voltage;
- `hrv_sdnn` uses RR-interval mean and standard deviation rather than a clearly
  defined SDNN result;
- `eda_scr_count` stores an average indicator rather than an event count;
- `eda_phasic_amplitude` falls back to mean conductance;
- missing respiration rate falls back to `60 / raw_amplitude`, which has no
  valid physiological interpretation.

Review goal:

- define the exact statistic and unit for every configured signal component;
- remove misleading fallbacks;
- explicitly represent unavailable components;
- avoid persisting a proxy under the name of a different physiological metric;
- decide which metrics are valid for the MVP without adding heavyweight signal
  processing dependencies.

### 5. Tenancy Scoping Is Optional in Practice

ARC functions accept `sponsor_id`, but it defaults to `None`. Their SQL then
disables sponsor filtering when no sponsor is supplied. The production
session-close caller currently invokes ARC with only `session_id`.

Review goal:

- require `sponsor_id` at application-facing ARC entry points;
- pass it from session close;
- scope all session, ECHO, biosignal, and baseline reads by tenancy;
- add wrong-sponsor integration tests.

### 6. Filtered Preflight Checks Unfiltered ECHO Events

The preflight ECHO count applies configured anchor filters, but the
nearest-sample query evaluates all ECHO events for the session. A distant event
that is not eligible to open an ARC window can therefore block ARC.

Review goal:

- apply the same anchor predicate to bounds, counts, and nearest-sample queries;
- add a test where selected anchors align but an excluded event does not;
- confirm the report describes only the evaluated anchor population.

### 7. Frozen ARC Models Contain Mutable State

Some frozen dataclasses contain mutable dictionaries. In particular,
`ARCTemporalAlignmentReport.streams` can be changed after validation. An empty
dictionary passed as `APEXResponse.metadata` also avoids conversion to an
immutable mapping.

Review goal:

- decide whether these objects promise true immutability;
- use immutable mappings or defensive copies if they do;
- test mutation attempts and serialization stability.

## Suggested Review Order

1. Establish the lifecycle: reconciliation, watermark verification, preflight,
   ARC processing, and terminal failure handling.
2. Define transaction boundaries and rollback behavior.
3. Make sponsor/site tenancy mandatory through the complete ARC call chain.
4. Correct filtered-anchor preflight semantics.
5. Audit every signal-component calculation, unit, and fallback.
6. Tighten model validation and immutability.
7. Expand integration tests around the corrected contracts.

## Verification Checklist

- ARC cannot start without `watermark_verified`.
- Unreconciled sessions produce no baseline or convergence artifacts.
- Temporal misalignment blocks ARC before writes begin.
- An ARC database exception rolls back and leaves the session `failed`.
- Wrong-sponsor calls return no data and produce no writes.
- Excluded ECHO events do not affect filtered preflight results.
- Every persisted component name matches its implemented statistic and unit.
- Missing signals are represented explicitly rather than inferred from
  unrelated values.
- Re-running ARC is deterministic and idempotent.
- ARC tests cover the production session-close handoff, not only direct helper
  calls.

## Current Test Signal

At the time of this review:

- 94 non-integration ARC tests passed;
- Ruff passed for `batch/arc` and its tests;
- 14 ARC integration tests were not run because they require a configured test
  database.

Passing unit tests do not resolve the lifecycle, transaction, tenancy, or
physiological-semantics findings above.
