# Spec: ARC Processor

## Metadata
- **Task**: arc-processor
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`batch/arc/processor.py` is the ARC post-session computation layer. It loads ECHO marker events from the DB, applies debounce clustering to select canonical anchors, computes per-modality signal baselines from raw biosignal tables over a configurable baseline window, and persists the results via idempotent upsert into `session_baselines`. The public entry point is `run_arc_post_session`, which wraps all errors as `ARCPostSessionError`. Raw `echo_events` rows are never mutated — ARC only reads them. The baseline window starts at the earliest biosignal sample for the session and spans `baseline.window_duration_s` from the config.

DB-reading entry points are tenancy-scoped: `load_echo_anchor_rows`, `compute_session_baseline_rows`, and `_query_session_meta` take `sponsor_id` as the third positional parameter (after `conn, session_id`) and filter session queries with `AND sponsor_id = %s` (see decisions.md "ARC Tenancy Scoping").

## Rules

### Cluster validation — unit tests

- **R-001** [unit]: `cluster_echo_anchor_rows` raises `ValueError` when `debounce_gap_s` is negative.

- **R-002** [unit]: `cluster_echo_anchor_rows` raises `ValueError` when `debounce_gap_s` is non-finite (`inf` or `nan`).

- **R-003** [unit]: `cluster_echo_anchor_rows` returns an empty tuple when given an empty sequence.

### Debounce clustering logic — unit tests

- **R-004** [unit]: Two rows whose `lsl_timestamp` gap is strictly less than `debounce_gap_s` end up in the same cluster.

- **R-005** [unit]: Two rows whose `lsl_timestamp` gap equals `debounce_gap_s` (boundary case) end up in the same cluster — the condition is `<=`, not `<`.

- **R-006** [unit]: Two rows whose `lsl_timestamp` gap is strictly greater than `debounce_gap_s` end up in different clusters.

- **R-007** [unit]: `cluster_echo_anchor_rows` sorts input rows by `(lsl_timestamp, id)` before clustering — unsorted input produces the same clusters as sorted input.

- **R-008** [unit]: `cluster_echo_anchor_rows` assigns sequential `index` values starting at 0 to each returned cluster.

### EchoAnchorCluster properties — unit tests

- **R-009** [unit]: `EchoAnchorCluster` raises `ValueError` when constructed with an empty `members` tuple.

- **R-010** [unit]: `EchoAnchorCluster.canonical_anchor` returns `members[0]` (the first member, i.e. the earliest-timestamp row).

- **R-011** [unit]: `EchoAnchorCluster.size` equals `len(members)`.

- **R-012** [unit]: `EchoAnchorCluster.start_lsl_timestamp` equals `members[0].lsl_timestamp` and `end_lsl_timestamp` equals `members[-1].lsl_timestamp`.

### Anchor filter — unit tests

- **R-013** [unit]: `_anchor_filter_pairs` returns `None` for `None` input and for an empty sequence.

- **R-014** [unit]: `_anchor_filter_pairs` returns a tuple of `(event_type, zone_label)` pairs for non-empty input, one pair per `AnchorEventFilter`.

### Baseline row builder — unit test

- **R-015** [unit]: `_build_baseline_row` returns `None` when `sample_count` in the stats tuple is `0` or negative — no zero-sample baseline rows are created.

### ECHO anchor loading — integration tests

- **R-016** [integration]: `load_echo_anchor_rows` returns rows for the given session ordered by `lsl_timestamp ASC, id ASC`.

- **R-017** [integration]: `load_echo_anchor_rows` with `anchor_filters` returns only rows whose `(event_type, zone_label)` pair matches at least one filter — rows that don't match are excluded.

- **R-018** [integration]: `load_echo_anchor_rows` with `anchor_filters=None` returns all rows for the session regardless of `event_type` or `zone_label`.

### Baseline persistence — integration tests

- **R-019** [integration]: `upsert_session_baselines` is idempotent — calling it twice with the same rows produces exactly one row per `(session_id, modality, signal_component)` in `session_baselines`.

- **R-020** [integration]: `upsert_session_baselines` is a no-op for an empty sequence — it returns without executing any SQL.

- **R-021** [integration]: `compute_session_baseline_rows` returns an empty tuple when no biosignal data exists for the session (all modality tables return no rows for the session).

- **R-022** [integration]: `compute_session_baseline_rows` raises `RuntimeError` when at least one modality has fewer samples than the configured `min_sample_count` threshold in the baseline window.

### ARC post-session orchestrator — integration tests

- **R-023** [integration]: `run_arc_post_session` writes baseline rows to `session_baselines` and returns an `ARCPostSessionResult` with `baseline_row_count` equal to the number of rows written.

- **R-024** [integration]: `run_arc_post_session` raises `ARCPostSessionError` (not the original exception type) when an unhandled exception is raised inside the pipeline — except for `ARCPostSessionError` itself, which propagates unchanged.

## Won't Do

- Test `_query_eeg_proxy_stats`, `_query_hrv_rmssd_stats`, `_query_eda_scr_stats`, etc. individually — their SQL is tested implicitly through `compute_session_baseline_rows`.
- Test that `echo_events` rows are never mutated — the function never issues UPDATE/DELETE; trust the read-only query.
- Test that `session_baselines` is the correct table for the upsert conflict key — that is a migration concern.

## Risks

- **`canonical_anchor_count` and `cluster_count` in `ARCPostSessionResult` always have the same value** — both are set to `len(clusters)`. The field naming implies a distinction (canonical selection may differ from cluster count) but the current implementation collapses them. Tests should assert `result.canonical_anchor_count == result.cluster_count` as a documentation of this invariant, not a correctness check.
- ~~`_query_session_meta` does not filter by `sponsor_id`~~ — **upgraded from accepted gap to requirement** (decisions.md "ARC Tenancy Scoping", June 2026): `_query_session_meta`, `load_echo_anchor_rows`, and `compute_session_baseline_rows` filter by `sponsor_id`, matching `mark_session_closing` / `mark_session_failed`.
- **`compute_session_baseline_rows` raises `RuntimeError` when any modality has too few samples** — this propagates through `run_arc_post_session` as `ARCPostSessionError`, which marks the session as failed. A session with sparse but valid data (e.g. EDA sensor disconnected early) will fail ARC entirely. Accepted as current design; mitigation is per-modality optional baseline configuration.

## Open Questions

- _(none)_
