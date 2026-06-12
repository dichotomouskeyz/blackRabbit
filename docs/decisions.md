# Decisions

## Operator UI — Staged Agentic Surface

- **Decision:** Build a researcher operator UI as a staged agentic surface:
  Next.js chat GUI (Vercel AI SDK, pinned tools) → thin FastAPI (`api/`) →
  existing `capture.*` / `batch.arc.*` contracts, plus a live biosignal tab
  (uPlot) over a FastAPI WebSocket and an ARC review tab. This reintroduces the
  previously deferred thin FastAPI + WebSocket (see "Real-Time Delivery"), but
  **staged by capability status** (`scaffolded` / `blocked` / `implemented`).
  The contract authority is `.correctless/specs/operator-ui.md` (HIGH intensity).
- **Rationale:** The backend has no user surface, but exposing unfinished
  capture/ARC through an agent multiplies risk where the backend is least settled
  (ARC still gateable before `watermark_verified`, capture process ownership
  unsettled, localhost tenancy is not authentication). Staging ships a usable,
  low-risk shell now and gates write/exec capabilities behind the open questions.
- **Code impact:**
  - The API **wraps** the §1 contracts in `docs/ui-integration.md`; it never
    duplicates their logic. Any direct SQL is **read-only and parameterized** — a
    small read query module, **no `SessionRepository`**; write paths stay direct
    workflow wrappers.
  - The model never supplies `sponsor_id`, SQL, shell, or arbitrary endpoint
    paths. **FastAPI owns tenant context and authorization** (server-injected).
  - Blocked capabilities are non-executable (disabled tools): endpoints are
    *present* and fail closed with a structured `409 Capability unavailable`
    body before any DB call; the scaffolded WS refuses the upgrade. Milestone 0
    ships health/capabilities/vocab/list/status/create on the API; the visual
    shell (tabs + status-flagged tool registry) is deferred to the frontend
    feature (see `docs/2R/backlog.md` "Operator UI — Deferred / Skipped
    Register").
  - New `api/` and `web/` trees; new env vars (`ANTHROPIC_API_KEY`,
    `API_BASE_URL`, `NEXT_PUBLIC_API_URL`). The formal `TB-004` (client→API) and
    capability-gating `PAT` land via `/cupdate-arch` after implementation.
- **Date:** June 2026

## Operator UI M0 — Accepted DoS Risk

- **Decision:** For operator-UI M0, connection/WS volume caps (BND-004) are NOT
  implemented. The connection-exhaustion DoS — repeated `POST /sessions` (no
  pooling, `docs/ui-integration.md` §2) and WS connections exhausting DB
  connections — is **explicitly accepted as an unmitigated M0 risk**. The
  graceful path under exhaustion is the 503 `psycopg2.OperationalError` handler
  (QA-001 / INV-014): exhaustion surfaces as `503 {"error":"backend_unavailable"}`,
  never a raw 500.
- **Rationale:** M0 is localhost-bound with the client co-located on the same
  host and no authentication (EA-001/EA-003). The attack surface is a local
  operator, so DoS impact is low and a connection cap adds complexity without
  M0 security value. BND-004 permits a documented-acceptance branch rather than
  full mitigation; this is that acceptance. The cap is revisited before any
  exposure beyond localhost or any write/exec unblock (OQ-001).
- **Code impact:**
  - No connection cap or WS-per-host cap is added in M0.
  - The app-level `psycopg2.OperationalError` handler in `api/app.py` returns
    `503 {"error":"backend_unavailable", "message":...}` for every DB-touching
    route, so exhaustion fails closed with an actionable message (INV-014).
  - Revisit (add a bounded acquire returning 503 on exhaustion + a WS cap) is
    gated on OQ-001 / non-localhost exposure.
- **Date:** June 2026

## Operator UI Pipeline — Backend Debt Deferred

- **Decision:** The `operator-ui` pipeline (verify → arch → docs → PR) proceeds
  against the scoped `tests/api_tests` suite. Two items are explicitly deferred
  rather than gating the UI track:
  1. The **10 pre-existing capture-layer test failures** (ECHOWriter signature
     drift ×5, ARC baseline-persistence fixture ×4, session_close r021 ×1) are
     backend debt that predates this feature and is unrelated to `api/`. They
     are user-gated fixture work tracked in `docs/2R/backlog.md`
     ("User-Gated Test Work") and must be fixed before the next backend feature.
  2. The **`/creview-spec` re-run** for the +44-line post-approval spec drift
     (421 → 465 lines) is skipped. Those lines are the QA-audit-driven contract
     upgrades (QA-001..QA-006: 503 `backend_unavailable` mapping, tenancy-not-
     configured 503, BND-004 acceptance note, closed-SQL scan generalization) —
     adversarially derived, implemented, and pinned by tests (70/70 green).
- **Rationale:** Both items would block the UI track on work that is either
  backend-owned (the fixtures) or already reviewed by the audit that produced
  it (the spec delta). Deferring keeps the pipeline honest: the deferral is
  recorded here, in the backlog, and in the Correctless override log, and the
  full-suite test gate is restored at docs time so the debt stays visible (red
  gate) until paid.
- **Code impact:** `.correctless/config/workflow-config.json` `commands.test`
  restored from `uv run pytest tests/api_tests` to `uv run pytest` when the
  pipeline reaches `documented`. No application code changes. Skipped/deferred
  register: `docs/2R/backlog.md` "Operator UI — Deferred / Skipped Register".
- **Date:** June 2026 (2026-06-12)

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
