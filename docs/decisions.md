# Decisions

## Hardware - 1a Development Environment

- **Decision:** 1a development uses simulated LSL streams by default.
- **Rationale:** Simulated streams keep the MVP self-contained, reproducible,
  and hardware-agnostic. Any LSL-compatible device can be substituted later if a
  research deployment needs it.
- **Deferred:** Device selection for EEG, HRV, EDA, and respiration.
- **Code impact:** Capture commands must work the same way against simulated
  and real LSL streams. Stream names and sample rates come from
  `config/settings.py`.
- **Date:** April 2026

## Safety Thresholds

- **Decision:** Live safety-monitor semantics are deferred from the research MVP.
- **Rationale:** Thresholds that imply participant intervention need domain
  validation and should not be presented as product behavior in the local MVP.
- **Current behavior:** Placeholder safety modules may exist, but the active
  Phase 2 path is capture, XDF backup, reconciliation, and post-session
  analysis.
- **Code impact:** Do not hardcode safety thresholds into capture code. Any
  future monitor must be configuration-driven and explicitly scoped.
- **Date:** April 2026; reframed May 2026

## Real-Time Delivery

- **Decision:** Broad real-time delivery and coordinator UI work are deferred.
- **Rationale:** The current path is local capture plus post-session ARC
  processing. A larger API/UI surface would add maintenance cost before the
  batch contracts are stable.
- **Deferred:** Broad FastAPI service, WebSocket event stream, and React
  coordinator UI.
- **Code impact:** Keep capture and batch interfaces CLI-friendly and
  replayable. If an API is introduced later, it should wrap existing contracts
  instead of replacing them.
- **Date:** April 2026; reframed May 2026

## ARC Tenancy Scoping

- **Decision:** ARC batch reads (`validate_arc_temporal_alignment`,
  `assert_arc_temporal_alignment`, `load_echo_anchor_rows`,
  `compute_session_baseline_rows`, `_query_session_meta`) take a `sponsor_id`
  parameter and filter their session queries by it. The former
  "accepted defense-in-depth gap" in `.correctless/specs/arc-processor.md` is
  upgraded to a requirement.
- **Rationale:** The watchdog spec (R-012) already requires tenancy on
  `alert_events` writes, and repo rules mandate that application queries
  preserve tenant boundaries. UUID session IDs make collisions unlikely, but
  read paths should not be the one place tenancy is skipped.
- **Code impact:** `batch/arc/preflight.py` and `batch/arc/processor.py` gain an
  optional `sponsor_id` parameter (default `None`; filter applied when provided)
  threaded into their SQL. `batch/reconciliation/db.py:close_session` gains the
  same guard on its UPDATE. Reconciliation reads (`fetch_session_meta`,
  `fetch_existing_sample_indices`) are a follow-up sweep, not part of this
  change.
- **Date:** June 2026

## Spec-vs-Implementation Drift Resolution (Test Suite Regen)

- **Decision:** `.correctless/specs/` is the contract authority. The regenerated
  test suite's 46 failures were resolved case-by-case: implementations were
  found spec-faithful, so fixes go into the implementation only where the spec
  (or an explicit spec upgrade) requires it; tests are never hand-edited.
- **Rationale:** Hand-editing spec-derived tests to match code inverts TDD.
  Audit showed tests overreached the spec (ARC `sponsor_id`, `ECHOWriter(cfg)`)
  or guessed spec-silent incidentals (str vs `Path`, `lsl_ts` naming, arg
  order, constant location). Spec-silent incidentals were pinned in the specs
  first, then implemented.
- **Current behavior:** F1/F2/F3/F5/F6/F7/F8/F9 resolved in implementation.
  F4 (`ECHOWriter` constructor, 5 tests) is left red: the spec says the writer
  is buffer-only, the test wrongly passes a config, and fixing it requires a
  test change — deferred to user-gated spec-driven test regeneration.
- **Code impact:** Validation precedes DB connects in `session_init`;
  `watchdog.log_restart` is non-fatal; selected ARC entry points accept sponsor
  scope; session
  close coerces path-like input; reconciliation uses canonical `lsl_timestamp`
  naming and `(conn, session_id, table)` argument order; `BUFFER_MAX_CHUNKS`
  is importable from `stream_db`.
- **Date:** June 2026

## StreamThread Owns Its Runtime Resources

- **Decision:** `StreamThread` owns its DB connection (`thread.conn`), LSL
  inlet (`thread.inlet`), and mutable runtime state (`StreamThreadState`:
  buffer, sample_index, chunk_count, last_drift_ts, fatal_error). Helper
  functions take the thread only — `write_rows(thread, rows)`,
  `flush_buffer(thread)`, `maybe_record_drift(thread, now_lsl=None)` — instead
  of passing the connection through every call.
- **Rationale:** The connection was a local variable threaded through six
  helper modules ("hot potato"), while the buffer and counters already lived
  on the thread. Thread-owned state matches the forwarder spec's vocabulary
  ("the connection is set to None") and the spec-derived tests, removes ~40
  private-field reaches across helper modules, and simplifies every call site.
- **Current behavior:** A non-operational `psycopg2.Error` during a chunk
  write rolls back, logs at ERROR, drops the chunk, and keeps the connection —
  restoring the forwarder spec's accepted design (XDF retains the chunk for
  reconciliation at close). This reverts the fail-stop RuntimeError introduced
  in `ac4fb1f`; sample+integrity writes remain a single transaction.
  `OperationalError` still buffers and nulls the connection. Chunk inserts use
  per-row `cur.execute` from a closed SQL mapping keyed by `stream_type`.
- **Code impact:** `capture/forwarder/stream_thread/` — `stream_thread.py`
  (state dataclass + properties), `stream_db.py`, `stream_drift.py`,
  `stream_chunks.py`, `stream_runtime.py`, `stream_inlet.py`,
  `stream_integrity.py`. `build_stream_threads(cfg, stop, xdf)` and external
  callers unchanged.
- **Date:** June 2026

## Session-Init Abstractions Deferred Until the UI Exists

- **Decision:** `SessionRequest` (typed request dataclass) and
  `SessionRepository` (persistence layer) from
  `docs/_archive/phase-2-reviews/refactors/session_init_refactors.md` are
  deferred until the UI/API layer exists. The metadata "shadow schema" fix
  went ahead:
  `_null_metadata_fields()` was replaced by the `SignalMetadataRow` dataclass
  (`capture/session_init/metadata.py`) while keeping the pinned kwargs/dict
  contracts.
- **Rationale:** Both ends of the session-init chain are spec-pinned kwargs
  contracts (`create_session(...)` R-001–004; `_build_metadata_rows(...)`
  R-005–008), so a request object would be built from kwargs and unpacked
  back to kwargs one call later — a decorative layer with no consumer.
  Validation already runs pre-DB at the top of `create_session`. These
  abstractions get designed against the real UI/API request shape instead of
  speculation.
- **Code impact:** None today. `docs/ui-integration.md` is the living home
  for UI↔backend connection concerns and carries the revisit checklist.
- **Date:** June 2026

## Local Model Agent Neutrality

- **Decision:** The repo does not hardwire a local-model coding agent.
- **Rationale:** Local model work may use LM Studio, LiteLLM, Continue, Claude
  Code, Codex, or another coding agent while the workflow is still being tested.
- **Current behavior:** Repo docs only record the common local endpoint shape:
  LM Studio serving an OpenAI-compatible API at `http://localhost:1234/v1`.
- **Code impact:** Keep model/provider config out of application code. User-level
  files such as `C:\Users\jahlo\.continue\config.yaml` and
  `C:\Users\jahlo\.claude\litellm\config.yaml` stay outside repo ownership.
- **Date:** June 2026
