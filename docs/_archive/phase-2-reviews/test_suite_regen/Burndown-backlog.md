# Burn-down backlog — branch 2R (spec-first)

Queue + state for the burn-down loop. Rules: **no test file is ever created or edited**; no new migrations (edit existing + rebuild DB); working tree only (user commits at phase boundaries); important decisions → `docs/decisions.md`.

Status: ☐ open · ◐ in progress · ☑ done · ⚑ flagged for user

## Phase 0 — Spec reconciliation + decision records

- ☑ 0.1 `docs/decisions.md`: "ARC Tenancy Scoping" + "Spec-vs-Implementation Drift Resolution" entries
- ☑ 0.2 `arc-preflight.md`: `sponsor_id` (optional 3rd param) + R-016 + conventions (lowercase stream names, streams iteration, list-tolerant filters)
- ☑ 0.3 `arc-processor.md`: `sponsor_id` on `load_echo_anchor_rows`/`compute_session_baseline_rows`/`_query_session_meta`; line-89 gap → requirement
- ☑ 0.4 `session-close.md`: `run()` accepts path-like, coerces to `Path`
- ☑ 0.5 `reconciliation.md`: `lsl_timestamp` naming; `(conn, session_id, table)` order; close_session/write_reconciliation_log/run_backfill/_build_backfill_rows signatures pinned
- ☑ 0.6 `forwarder.md`: `BUFFER_MAX_CHUNKS` importable from `stream_db`

## Phase 1 — Suite green via implementation-only fixes

- ☑ 1.1 F8: validate before DB connect — `capture/session_init/workflow.py` (compound/participant UUID/dose unit → ValueError pre-connect)
- ☑ 1.2 F9: `log_restart` non-fatal — `capture/watchdog/db.py` (connect + lookup_compound inside try)
- ☑ 1.3 F2/F3: optional `sponsor_id` + NULL-tolerant filter — `batch/arc/preflight.py` (3 query helpers), `batch/arc/processor.py` (rows/clusters/canonical/meta/baselines/run_arc_post_session). Also: list-tolerant anchor_filters, `_anchor_filter_pairs` accepts plain pairs, report streams normalize dict→tuple, lowercase stream names.
- ☑ 1.4 F5: `lsl_ts` → `lsl_timestamp`
- ☑ 1.5 F6: `fetch_existing_sample_indices(conn, session_id, table)`
- ☑ 1.6 F1: `run(session_id, sponsor_id, xdf_path: str | Path)` coerces to Path
- ☑ 1.7 F7: `BUFFER_MAX_CHUNKS` re-exported from `stream_db`
- ☑ 1.10 Second-layer reshapes (test-encoded, spec-pinned in 0.5): `close_session(conn, session_id, sponsor_id=None, is_reconciled=...)` + tenancy guard; `write_reconciliation_log(conn, report, meta=None)`; `run_backfill(conn, report, xdf_path=None, meta=None, ...) -> int`; `_build_backfill_rows(stream_name, meta, ...)`; module-attr call for write_reconciliation_log in `capture/session_close/reconciliation.py` (late binding). Callers updated: `capture/session_close/workflow.py`, `capture/session_close/reconciliation.py`, `batch/reconcile.py`.
- ⚑ 1.8 FLAGGED RED — need user-gated test changes (14 tests):
  - F4 echo_handler (5): test passes a cfg to `ECHOWriter()`; spec R-013/14/15 say buffer-only.
  - arc_config placeholder (4): `tests/capture_tests/arc/conftest.py:arc_config` is a SimpleNamespace that matches neither `ARCWatchdogConfig` (`.raw`, `.anchor_events`) nor the loader; conftest itself says "Phase D wires this to the project's real config loader". r019/r021/r022/r023.
  - chunk_drift (4): tests encode the post-refactor stream_thread architecture (`thread.conn` attribute, `write_rows(thread, rows)`, `flush_buffer(thread)`, `maybe_record_drift(thread, now_lsl=...)`, `thread._last_drift_ts`, `thread.inlet`). Belongs to Phase 2.1–2.4; revisit then.
  - session_close r021 (1): test bug — fixture builds `_tracking_run` but never `monkeypatch.setattr`s it, so `conn_closed` can never flip (`conftest.py:191-196`).
- ☑ 1.9 Full suite + ruff (impl dirs clean; pre-existing I001 import-sort errors exist in tests/capture_tests/schema + xdf — untouchable). **PAUSED — user review/commit.**

## Phase 2 — Refactors (each doc's own order/non-goals)

- ☑ 2.1 stream_thread: `StreamThreadState` dataclass + public properties + mutation methods; thread-owned `conn`/`inlet`/`log` (decided with user; decisions.md "StreamThread Owns Its Runtime Resources")
- ☑ 2.2 stream_thread: `stream_inlet`/`stream_drift`/`stream_runtime` on public surface; `maybe_record_drift(thread, now_lsl=None)`; runtime loop rewired to `thread.conn`/`thread.inlet`
- ☑ 2.3 stream_thread: `stream_db` rewritten — `write_rows(thread, rows)`/`flush_buffer(thread)`/`connect_db`/`try_reconnect` set `thread.conn`; per-row `cur.execute` from closed SQL map; non-operational `psycopg2.Error` → rollback+drop+keep conn (spec-accepted; reverts `ac4fb1f` fail-stop); `stream_integrity` no-ops without integrity config
- ☑ 2.4 stream_thunks: `process_chunk(thread, samples, timestamps)`; `build_rows`/`buffer_chunk` keep test-pinned private access. Side effect: the 4 ⚑ chunk_drift tests are now GREEN (flag list shrinks to 10)
- ✗ 2.5 session_init `SessionRequest` — DEFERRED until UI/API exists (both boundaries are spec-pinned kwargs contracts; decisions.md "Session-Init Abstractions Deferred"; revisit checklist in `docs/ui-integration.md`)
- ☑ 2.6 session_init: `SignalMetadataRow` dataclass replaces `_null_metadata_fields()` shadow schema; pinned kwargs/dict contracts unchanged
- ✗ 2.7 session_init `SessionRepository` — DEFERRED with 2.5 (same decision)
- ☑ 2.7b `docs/ui-integration.md` created — living doc for UI↔backend contracts, deferrals, and the when-UI-lands checklist
- ☑ 2.8 preflight: `run_preflight(cfg)` wrapper shares one connection; `verify_session_ready`/`load_session_config` take `conn`; `settings.REQUIRED_MODALITIES` (env-overridable CSV); typed exceptions `SessionNotFoundError`/`SessionNotActiveError`/`MissingModalityError` (RuntimeError subclasses)
- ☑ 2.9 `ForwarderEngine` with prepare/start/run_until_stopped/stop phases; `run_forwarder` is the thin wrapper; helpers `join_threads`/`raise_if_thread_failed` kept as module functions. **PAUSED — user review/commit.**
- ✗ xdf constants registry — excluded until next modality lands
- 📝 leftover (not done, from forwarder-refactors.md): attach `CAPTURE_SOURCE` to every log entry via a logging context — touches `capture/logger` which has its own pinned tests; do as its own small item

## Phase 3 — Doc/hygiene sync

- ☑ 3.1 db-health §1.7 chain listing corrected to true head `030`
- ☐ 3.2 SCHEMA.md sweep incl. committed 019 duplicate-column fix
- ☐ 3.3 Delete legacy test-dir husks (`tests/echo_handler*`, `tests/reconcile_test`, `tests/unit`, `tests/integration`)
- ☐ 3.4 `.gitignore`: add `.correctless`, `.coverage`. **PAUSE — user review/commit.**

## Run log

| When | Item | Suite line |
|---|---|---|
| 2026-06-10 baseline | — | 46 failed, 261 passed, 4 skipped |
| 2026-06-10 Phase 0+1 complete | 0.1–0.6, 1.1–1.7, 1.10 | 14 failed, 293 passed, 4 skipped (all 14 are ⚑ 1.8 flagged — no fixable red remains) |
| 2026-06-11 stream_thread refactor | 2.1–2.4 | 10 failed, 297 passed, 4 skipped (chunk_drift ⚑ now green; remaining red: 5 echo F4 + 4 arc_config + 1 session_close r021) |
| 2026-06-11 Phase 2 complete | 2.5✗ 2.6☑ 2.7✗ 2.7b☑ 2.8☑ 2.9☑ | 10 failed, 297 passed, 4 skipped (unchanged — all remaining red is user-gated ⚑) |
