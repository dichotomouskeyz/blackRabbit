# ARC

ARC is Agentic Response Convergence, the synchronized post-session convergence
layer between ECHO and APEX.

## Implementation Status

ARC is currently prototype scaffolding, not a complete or validated batch
processing implementation. The existing models, window helpers, temporal
preflight, anchor clustering, and baseline persistence establish preliminary
contracts only. ARC output must not yet be treated as validated research
output.

### Mandatory Batch Entry Gate

ARC must never begin until all of the following are true:

1. Capture has stopped and the XDF file is closed.
2. XDF-to-database reconciliation has completed successfully.
3. Recoverable gaps have been backfilled and reconciliation has been rerun.
4. The session has transitioned to `closed`.
5. The database has emitted `watermark_verified`.
6. ARC temporal preflight has passed for the tenancy-scoped session and the
   selected ECHO anchors.

An unreconciled, failed, active, closing, or unverified session must produce no
ARC baselines, convergence profiles, or other ARC artifacts. This lifecycle
requirement takes precedence over the current implementation, which does not
yet enforce the complete sequence.

### Missing Specification Work

A complete ARC specification must still define:

- the authoritative batch entry point and watermark-verification query;
- transaction ownership, rollback behavior, idempotency, and terminal failure
  handling;
- mandatory sponsor and site tenancy across every read and write;
- whether ARC windows are centered or sequential post-event ranges;
- exact ECHO anchor filtering and debounce semantics;
- temporal preflight behavior for filtered anchors and missing modalities;
- the exact algorithm, unit, sample requirements, and provenance for every
  APEX feature;
- baseline selection, validity, and unavailable-signal representation;
- W1/W2/W3 observed-response calculations;
- z-score, p-value, effect-direction, and convergence-density calculations;
- permutation null-model execution and deterministic random seeding;
- Benjamini-Hochberg family construction and FDR handling;
- persistence rules for passing and non-passing events;
- replay, rerun, versioning, and conflict behavior;
- query and operator-review requirements for ARC artifacts.

### Required Evaluation

Before completing ARC, evaluate:

- which physiological features are scientifically defensible for the MVP
  without heavyweight dependencies;
- whether all four modalities are mandatory or partial sessions are valid;
- minimum sample counts and signal-quality requirements per feature;
- how missing, disconnected, sparse, or invalid signals affect ARC;
- whether the existing schema can represent unavailable and failed
  calculations honestly;
- event-window query performance over expected session sizes;
- transaction isolation and recovery after partial database failure;
- whether the current models and tables should remain stable after the
  algorithm is finalized;
- what constitutes a validated ARC result for research use.

### Current Development Boundary

Until the complete specification is approved:

- do not expand or refactor ARC solely to formalize the current structure;
- do not add proxy calculations under physiological metric names;
- do not automatically execute ARC from session close;
- preserve the existing ARC package as prototype scaffolding;
- limit ARC work to documentation, review, and narrowly required safety
  gating.

Detailed known implementation findings are recorded in
`docs/future_implementation/arc-review.md`. The current
`.correctless/specs/arc-*.md` files describe preliminary contracts and require a
dedicated specification review before they can represent the complete ARC
pipeline.

## Canonical Convergence Event

The canonical in-memory object is `ARCConvergenceEvent` in `batch.arc.models`.
It defines the proposed shape of one event-locked convergence result:

| Layer | Object | Role |
|-------|--------|------|
| ECHO | `EchoAnchorEvent` | The behavioral/context event that opens ARC windows. It carries the `echo_events.id` foreign key, identity fields, event vocabulary, actor context, and LSL timestamp. |
| APEX | `APEXResponse` | One physiological component response inside one ARC window, including modality, signal component, baseline, observed value, sample count, z-score, p-value, and direction. |
| ARC | `ARCWindowResponse` | All APEX responses for one configured window (`w1`, `w2`, `w3`) plus that window's convergence density. |
| ARC | `ARCConvergenceEvent` | The synchronized object linking one ECHO anchor to all three APEX response windows, available/participating signal lists, FDR result, temporal alignment score, and config provenance. |

Proposed required shape:

- Exactly one ECHO anchor event.
- Exactly three ordered ARC windows: `w1`, `w2`, `w3`.
- APEX responses must declare the same window as their containing `ARCWindowResponse`.
- `passed_fdr` must be `True` before serialization to durable `event_composite_profiles`.
- `arc_config_version` and `arc_config_sha256` are both required.

Proposed serialization:

`ARCConvergenceEvent.to_event_composite_profile_row()` returns the insert contract
for `event_composite_profiles`. That row contains:

- identity fields copied from the ECHO anchor;
- `echo_event_id` as the durable ECHO foreign key;
- per-window convergence densities;
- per-window participating signal IDs such as `hrv.hrv_rmssd`;
- nested `deviation_metrics` keyed by window and signal ID;
- available/participating signal lists;
- FDR, temporal alignment, and ARC config provenance.

This object is intentionally processor-neutral. It defines the handoff between
future ARC computation and the existing append-only schema; it does not compute
APEX features, null models, or FDR correction itself.

## Temporal Alignment Gate

The completed ARC pipeline must call
`batch.arc.preflight.assert_arc_temporal_alignment()` before processing begins.
The helper exists, but the current runtime does not yet connect it as a
mandatory gate.

The gate verifies synchronized LSL time between ECHO and APEX:

- at least one ECHO anchor event exists;
- each required APEX stream (`EEG`, `HRV`, `EDA`, `Respiration`) has samples;
- for every ECHO event, each APEX stream has a nearest sample less than `1.0s`
  away in `lsl_timestamp`;
- failures name the APEX stream whose nearest-sample delta is not sub-second.

This check is separate from clock drift logging. Drift logging records clock
correction provenance during capture; the ARC temporal alignment gate verifies
the actual stored ECHO/APEX timestamps that the convergence processor would use.

## Signal Availability

The MVP does not run a separate live signal-availability layer. The intended
ARC contract considers a signal active when session metadata declares the
modality and the relevant analysis window contains valid samples for that
modality or component. The complete validity and missing-signal rules remain to
be specified.

`config/arc_watchdog_config.toml` still keeps a
`[signal_availability_profile]` section as a reserved config contract. The
loader validates it so config files remain explicit, but the current processor
uses complete post-session records rather than live SAP state.

## ECHO Anchor Clustering

ARC keeps raw `echo_events` rows unchanged, but it does not treat every raw
marker as a separate convergence trigger.

- ARC first filters rows to anchor-eligible ECHO events.
- Eligible rows are sorted by `lsl_timestamp`.
- Nearby rows are grouped with a debounce window before ARC opens windows.
- The first row in each cluster becomes the canonical ARC anchor.

The default debounce window is 10 seconds. This keeps back-to-back markers from
creating duplicate ARC episodes while preserving the full raw audit trail.

If ARC post-session processing throws, session close records an
`alert_events` row with `alert_type = 'arc_failure'`. A clean ARC run that
produces zero output is not treated as a failure.

## W1/W2/W3 Window Helpers

`batch.arc.windows` defines reusable centered LSL-time windows around an ECHO
timestamp:

| Window | Label | Width | Helper |
|--------|-------|-------|--------|
| `w1` | narrow | 30s | `centered_w1(echo_lsl_timestamp)` |
| `w2` | medium | 120s | `centered_w2(echo_lsl_timestamp)` |
| `w3` | wide | 300s | `centered_w3(echo_lsl_timestamp)` |

Use `centered_arc_windows(echo_lsl_timestamp)` when all three ordered windows
are needed. Each helper returns `ARCWindowBounds` with absolute
`start_lsl_timestamp` and `end_lsl_timestamp` values suitable for half-open SQL
ranges:

```sql
lsl_timestamp >= start_lsl_timestamp
AND lsl_timestamp < end_lsl_timestamp
```

These centered helpers conflict with the current ARC configuration, which
describes sequential post-event windows (`0-30s`, `30-120s`, and `120-300s`).
The complete specification must choose one window model before response
processing is implemented.
