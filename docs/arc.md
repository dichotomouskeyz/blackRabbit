# ARC

ARC is the synchronized convergence layer between ECHO and APEX.

## Canonical Convergence Event

The canonical in-memory object is `ARCConvergenceEvent` in `batch.arc_models`.
It represents one event-locked convergence result:

| Layer | Object | Role |
|-------|--------|------|
| ECHO | `EchoAnchorEvent` | The behavioral/context event that opens ARC windows. It carries the `echo_events.id` foreign key, identity fields, event vocabulary, actor context, and LSL timestamp. |
| APEX | `APEXResponse` | One physiological component response inside one ARC window, including modality, signal component, baseline, observed value, sample count, z-score, p-value, and direction. |
| ARC | `ARCWindowResponse` | All APEX responses for one configured window (`w1`, `w2`, `w3`) plus that window's convergence density. |
| ARC | `ARCConvergenceEvent` | The synchronized object linking one ECHO anchor to all three APEX response windows, SAP signal lists, FDR result, temporal alignment score, and config provenance. |

Required shape:

- Exactly one ECHO anchor event.
- Exactly three ordered ARC windows: `w1`, `w2`, `w3`.
- APEX responses must declare the same window as their containing `ARCWindowResponse`.
- `passed_fdr` must be `True` before serialization to durable `event_composite_profiles`.
- `arc_config_version` and `arc_config_sha256` are both required.

Serialization:

`ARCConvergenceEvent.to_event_composite_profile_row()` returns the insert contract
for `event_composite_profiles`. That row contains:

- identity fields copied from the ECHO anchor;
- `echo_event_id` as the durable ECHO foreign key;
- per-window convergence densities;
- per-window participating signal IDs such as `hrv.hrv_rmssd`;
- nested `deviation_metrics` keyed by window and signal ID;
- SAP available/participating signal lists;
- FDR, temporal alignment, and ARC config provenance.

This object is intentionally processor-neutral. It defines the handoff between
future ARC computation and the existing append-only schema; it does not compute
APEX features, null models, or FDR correction itself.

## Temporal Alignment Gate

Before ARC processing begins, `batch.arc_preflight.assert_arc_temporal_alignment()`
must pass for the session.

The gate verifies synchronized LSL time between ECHO and APEX:

- at least one ECHO anchor event exists;
- each required APEX stream (`EEG`, `HRV`, `EDA`, `Respiration`) has samples;
- for every ECHO event, each APEX stream has a nearest sample less than `1.0s`
  away in `lsl_timestamp`;
- failures name the APEX stream whose nearest-sample delta is not sub-second.

This check is separate from clock drift logging. Drift logging records clock
correction provenance during capture; the ARC temporal alignment gate verifies
the actual stored ECHO/APEX timestamps that the convergence processor would use.

## W1/W2/W3 Window Helpers

`batch.arc_windows` defines reusable centered LSL-time windows around an ECHO
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
