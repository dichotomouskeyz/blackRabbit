# Spec: ARC Preflight

## Metadata
- **Task**: arc-preflight
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`batch/arc/preflight.py` is the temporal alignment gate that must pass before ARC convergence profiles can be computed. For each required APEX stream, it finds the nearest biosignal sample to each ECHO anchor event and checks that the maximum nearest delta is strictly below a configurable threshold (default 1.0 s). ARC may only start when `is_aligned` is `True` on the returned report. `assert_arc_temporal_alignment` is the gating entry point — it calls `raise_for_unaligned()` and propagates a `RuntimeError` on failure.

Both entry points are tenancy-scoped: the signature is
`(conn, session_id, sponsor_id, *, threshold_s=..., required_streams=..., anchor_filters=None)`-shaped with `sponsor_id` the third positional parameter, and every session query carries `AND sponsor_id = %s` (see decisions.md "ARC Tenancy Scoping").

## Rules

### Input validation — unit test

- **R-001** [unit]: `validate_arc_temporal_alignment` raises `ValueError` when `threshold_s <= 0.0` or `threshold_s > 1.0` — the gate is always sub-second.

### `APEXStreamAlignment.is_aligned` — unit tests

- **R-002** [unit]: `APEXStreamAlignment.is_aligned` is `False` when `sample_count == 0`.

- **R-003** [unit]: `APEXStreamAlignment.is_aligned` is `False` when `max_nearest_echo_delta_s` is `None`.

- **R-004** [unit]: `APEXStreamAlignment.is_aligned` is `False` when `max_nearest_echo_delta_s >= threshold_s`.

- **R-005** [unit]: `APEXStreamAlignment.is_aligned` is `True` when `sample_count > 0` and `max_nearest_echo_delta_s` is finite and `< threshold_s`.

### `ARCTemporalAlignmentReport` — unit tests

- **R-006** [unit]: `ARCTemporalAlignmentReport.is_aligned` is `False` when `echo_event_count == 0`, even if all streams are individually aligned.

- **R-007** [unit]: `ARCTemporalAlignmentReport.is_aligned` is `False` when at least one stream's `is_aligned` is `False`.

- **R-008** [unit]: `ARCTemporalAlignmentReport.failed_streams` returns a sorted tuple of stream names whose `is_aligned` is `False`.

- **R-009** [unit]: `ARCTemporalAlignmentReport.raise_for_unaligned()` raises `RuntimeError` mentioning `"no ECHO anchor events found"` when `echo_event_count == 0`.

- **R-010** [unit]: `ARCTemporalAlignmentReport.raise_for_unaligned()` raises `RuntimeError` listing the failed stream names when ECHO events exist but streams fail alignment.

- **R-011** [unit]: `ARCTemporalAlignmentReport.raise_for_unaligned()` is a no-op (no raise) when `is_aligned` is `True`.

### Integration tests

- **R-012** [integration]: `validate_arc_temporal_alignment` returns a report with `echo_event_count` matching the number of ECHO events in the DB for the session (unfiltered when `anchor_filters=None`).

- **R-013** [integration]: When `anchor_filters` is provided, `validate_arc_temporal_alignment` counts only ECHO events whose `(event_type, zone_label)` pair matches at least one filter.

- **R-014** [integration]: When the max nearest delta for a stream is strictly below `threshold_s`, the stream's `is_aligned` is `True` in the returned report.

- **R-015** [integration]: `assert_arc_temporal_alignment` returns the report unchanged when alignment passes, and raises `RuntimeError` when it fails.

### Tenancy

- **R-016** [integration]: `validate_arc_temporal_alignment` and `assert_arc_temporal_alignment` take `sponsor_id` as the third positional parameter (optional, default `None` — filter applied when provided), and their ECHO/stream queries filter by `sponsor_id` in addition to `session_id` — a session queried under the wrong sponsor yields zero ECHO events (and therefore an unaligned report).

### Conventions

- Report stream names are lowercase modality form (`eeg`, `hrv`, `eda`, `respiration`), matching `session_signal_metadata.modality` and baseline modality keys.
- `ARCTemporalAlignmentReport.streams` iterates as `APEXStreamAlignment` objects; the constructor also accepts a `{name: alignment}` mapping and normalizes it.
- `anchor_filters` accepts any sequence of `(event_type, zone_label)` pairs (list or tuple).

## Won't Do

- Test `_query_max_nearest_echo_delta` SQL independently — it is an implementation detail of `validate_arc_temporal_alignment`; test the behavior through the public function.
- Test that `CROSS JOIN LATERAL` produces correct nearest-sample semantics — that is a PostgreSQL query plan correctness question, not a Python unit test.

## Risks

- **`validate_arc_temporal_alignment` computes max delta per stream but not per ECHO event** — if one ECHO event is far from the nearest biosignal sample (e.g. stream paused briefly), the max delta rises above threshold and ARC is blocked for the entire session. There is no per-event granularity. Accepted as a conservative gate.
- **`max_nearest_echo_delta_s` is computed only when both ECHO and stream have data** — if a stream has 0 samples, `max_nearest_echo_delta_s` is `None` and `is_aligned` is `False`. A session with a missing biosignal stream will always fail preflight. Accepted.

## Open Questions

- _(none)_
