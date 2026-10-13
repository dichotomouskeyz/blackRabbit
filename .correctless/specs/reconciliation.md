# Spec: Reconciliation

## Metadata
- **Task**: reconciliation
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`batch/reconciliation/` compares XDF sample counts against TimescaleDB counts after a session ends, optionally backfills missing samples from the XDF file, writes a reconciliation log entry, and closes the session. `batch/reconcile.py` is the CLI entry point and re-export compatibility layer — its behavior is covered here. The pipeline is: `read_xdf_counts` → `query_db_counts` → `build_report` → (optional) `run_backfill` → `query_db_counts` again → `build_report` again → `write_reconciliation_log` → `close_session`. Exit code 0 = reconciled, 1 = gaps remain, 2 = pre-condition error.

**Modules in scope:** `batch/reconcile.py`, `batch/reconciliation/models.py`, `batch/reconciliation/xdf.py`, `batch/reconciliation/db.py`, `batch/reconciliation/backfill.py`.

**Naming/signature conventions:** the canonical timestamp parameter name is `lsl_timestamp` (never `lsl_ts`), matching the column name used everywhere else. DB read/write helpers put `session_id` immediately after `conn`: `fetch_existing_sample_indices(conn, session_id, table)`, consistent with `query_db_counts` and `fetch_session_meta`.

Further pinned signatures (June 2026):
- Every session-scoped DB helper requires a non-empty sponsor scope. Optional `site_id` further narrows it; omitted sponsor is rejected before SQL. UUID session identifiers are not authorization.
- `close_session(conn, session_id, sponsor_id=None, is_reconciled=...)` rejects absent scope, updates exactly one scoped session, and raises if no row matches.
- `write_reconciliation_log(conn, report, meta=None, *, sponsor_id=..., site_id=None)` always checks canonical scoped session identity, including when callers supply metadata.
- `run_backfill(conn, report, xdf_path=None, meta=None, chunk_size=..., *, sponsor_id=..., site_id=None, legacy=False)` validates canonical session and XDF identity before writes; `xdf_path` defaults to the report's recorded path; returns the **total int** of rows inserted.
- `_build_backfill_rows(stream_name, meta, sample_index, lsl_timestamp, vals, session_id=None)` — meta is a `SessionMeta` or a mapping that may carry `session_id`/`device_id`.

## Rules

### Models — unit tests

- **R-001** [unit]: `StreamResult.gap` equals `xdf_count - db_count` (positive = DB missing samples, negative = XDF missed writes).

- **R-002** [unit]: `ReconciliationReport.is_reconciled` is `True` only when every stream's `gap` is exactly `0`.

- **R-003** [unit]: `ReconciliationReport.as_dict()` includes `session_id`, `xdf_path`, `is_reconciled`, `ran_at`, `max_clock_drift_s`, and a `streams` dict with `xdf_count`, `db_count`, and `gap` per stream.

### XDF reader — unit tests (with temp XDF files)

- **R-004** [unit]: `read_xdf_counts` raises `XDFReadError` when the file does not exist.

- **R-005** [unit]: `read_xdf_counts` raises `XDFReadError` when the first 4 bytes are not the XDF magic (`b"XDF:"`).

- **R-006** [unit]: `read_xdf_counts` raises `XDFTruncatedError` for missing footers on any declared stream, incomplete chunks, or truncated payload fields. Every header needs exactly one valid footer.

- **R-007** [unit]: `read_xdf_counts` returns `{stream_name: sample_count}` only after verifying footer counts against decoded samples. Duplicate stream IDs/names, invalid XML, non-finite timestamps, trailing malformed data, and count mismatches raise `XDFReadError`.

- **R-008** [unit]: `_read_chunk_length` returns `None` at EOF (empty read on first byte).

- **R-009** [unit]: Standard `_read_chunk_length` accepts only `{1, 4, 8}`. Width 2 is rejected. The explicitly requested `legacy=True` reader accepts the historical custom encoding; standard reads never silently switch formats.

- **R-010** [unit]: `stream_xdf_samples` yields `(sample_index, lsl_timestamp, channel_values)` only for the named target stream — other streams are skipped.

- **R-011** [unit]: `stream_xdf_samples` correctly skips ECHO marker samples (variable-length strings) when iterating past an ECHO chunk without yielding.

- **R-012** [unit]: `stream_xdf_markers` yields `(marker_index, lsl_timestamp, marker_text)` only for the `"ECHO"` stream — biosignal chunks are seeked past without decoding.

- **R-013** [unit]: `stream_xdf_samples` `sample_index` starts at 0 for the first sample of each stream and increments by 1 per sample across chunks (position in the file, not per-chunk).

Release reader contract approved 2026-10-13:
- **XDF-IDENTITY** [unit]: `validate_xdf_identity(path, session_id, sponsor_id, participant_id=None, site_id=None, *, legacy=False)` verifies complete structure, requires all five blackRabbit stream headers to agree on session/participant/site/sponsor identity, and compares supplied expected fields. It returns validated counts. Mismatch raises `XDFReadError` before any DB mutation.
- **XDF-METADATA** [unit]: `inspect_xdf(path, *, legacy=False)` returns counts, shared identity, per-stream metadata, and an explicit format label. Metadata cannot silently disagree between streams.
- **XDF-LEGACY** [unit]: Existing custom files remain untouched. Legacy decoding requires `legacy=True`; its width-2 integers, extra chunk wall clock, and bare timestamps are separately tested. Newly generated files are always standard XDF.

### DB helpers — integration tests

- **R-014** [integration]: `query_db_counts` returns sponsor-scoped distinct sample counts and ECHO row counts. When canonical EEG channel names exist, count only complete frames containing exactly those channel names, so a partially persisted EEG sample cannot reconcile as complete.

- **R-015** [integration]: `build_report` sets `is_reconciled=True` only when every stream in the union of XDF and DB streams has `gap == 0`; any positive or negative gap sets `is_reconciled=False`.

- **R-016** [integration]: `fetch_existing_sample_indices` returns a `frozenset[int]` of `sample_index` values already in the target biosignal table for the given session.

- **R-017** [integration]: `fetch_existing_echo_keys` returns a `frozenset` of 5-tuples `(lsl_timestamp, event_type, actor_id, actor_role, zone_label)`.

- **R-018** [integration]: `close_session` sets `sessions.status = 'closed'` and writes `closed_at` when `is_reconciled=True`; sets `status = 'failed'` when `False`. It requires sponsor scope, optionally site scope, and must update exactly one row. No match rolls back and raises without committing.

- **R-019** [integration]: `write_reconciliation_log` validates caller metadata against canonical scoped identity, then inserts exactly one row into `biosignal_integrity_log` with `log_type = 'xdf_reconciliation'` and the report serialized as JSONB. Mismatched participant/site/sponsor fails before insert.

### Backfill — integration tests

- **R-020** [unit]: `_build_backfill_rows` for `"EEG"` preserves canonical `eeg_channel_names` in order and rejects a width mismatch. Backfill obtains these names from persisted session metadata or the exact XDF header; conflicting sources fail closed. Only recordings with no names in either source may use the historical `ch_{i}` fallback.

- **R-021** [integration]: `_build_backfill_rows` for `"HRV"` sets `heart_rate_bpm = 60000.0 / rr_ms` when `rr_ms > 0`, and `None` when `rr_ms <= 0`.

- **R-022** [integration]: `_build_backfill_rows` raises `ValueError` for an unrecognized `stream_name`.

- **R-023** [integration]: `backfill_stream` skips existing biosignal samples. EEG skips existing `(sample_index, channel_id)` pairs and restores only missing channels of a partial frame.

- **R-024** [integration]: Backfill acquires the same session-level advisory lock as capture and close before checking existing rows, and retains it across chunk commits until connection close. A competing connection is rejected before insert. Replay is idempotent by existing sample/channel identities, not by assuming `ON CONFLICT DO NOTHING` provides a uniqueness constraint.

- **R-025** [integration]: `backfill_echo_markers` skips any marker whose composite key `(lsl_timestamp, event_type, actor_id, actor_role, zone_label)` is already present in `echo_events` or earlier in the pending replay batch.

- **R-026** [integration]: `run_backfill` only calls `backfill_stream` or `backfill_echo_markers` for streams with `gap > 0`; streams with `gap == 0` are skipped; streams with `gap < 0` (DB > XDF) log a WARNING and return 0 rows inserted.

- **R-027** [integration]: `run_backfill` routes the `"ECHO"` stream to `backfill_echo_markers` and all four biosignal streams to `backfill_stream`.

- **R-028** [unit/integration]: Every backfill entry point verifies canonical scoped participant/site/sponsor identity and XDF identity before inserting. Metadata supplied by callers is checked, not trusted. An absent or mismatched tenant, non-positive chunk size, malformed XDF, or conflicting channel/device identity fails before insert.

- **R-029** [unit]: The reconciliation CLI requires `--sponsor-id`, accepts optional `--site-id` and explicit `--legacy-xdf`, and obtains the session lock before validation/backfill. Missing or invalid scope is a precondition failure (exit 2); close/log writes cannot proceed unscoped.

## Won't Do

- Test that `stream_xdf_samples` decodes channel values as float32 — that is XDF format behavior, tested via round-trip with the XDF writer spec.
- Test `_BACKFILL_LOG_EVERY_N_COMMITS` log cadence — logging frequency is not a correctness invariant.

## Risks

- **`batch/reconciliation/backfill.py` imports `parse_echo_marker` from `capture.echo_handler`** — creates a cross-layer dependency (batch → capture). If the capture package is restructured, backfill breaks. Accepted for MVP; ECHO marker parsing logic lives in capture.
- **Negative gap (DB > XDF) is a silent warning** — if the DB has more rows than XDF (XDF write failures during capture), backfill is skipped and the reconciliation report marks `gap < 0`. The session is still closed as `failed`. The excess DB rows are not cleaned up. Accepted; the DB is the primary store and excess rows are valid captures.

## Open Questions

- _(none)_
