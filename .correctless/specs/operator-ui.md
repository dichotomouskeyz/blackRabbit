# Spec: Operator UI — Staged Agentic Surface

## Metadata

Release verification clarification (2026-10-13): tests that reload runtime
settings with optional variables absent must restore both environment and
module state before other tests execute. API integration checks must run with
a separately provisioned SELECT-only role on the isolated test database.
- **Created**: 2026-06-12T04:20:25Z
- **Status**: reviewed
- **Impacts**: session-init, forwarder, session-close, arc-processor, arc-preflight
- **Branch**: feature/phase-4-ui
- **Research**: null
- **Recommended-intensity**: high
- **Intensity**: high
- **Intensity reason**: new external network/WebSocket trust boundary (browser/LLM client → FastAPI, now TB-004); keyword `session`; TB-002 / TB-003 overlap; AP-001 (unvalidated IDs in query params) overlap; PII surface
- **Override**: none
- **Review**: `.correctless/artifacts/review-spec-findings-operator-ui.md` (RS-001..020 incorporated 2026-06-12)

## Context

The blackRabbit backend (capture + ARC batch) is built and spec-pinned but has no
user surface — operators drive it from the CLI. This spec is the single contract
authority for a researcher operator UI: a ChatGPT/Claude-style **agentic chat GUI**
for sessions (a Vercel AI SDK agent whose pinned tools drive existing backend
contracts), a **live biosignal tab** (uPlot charts + ECHO overlays) fed by a
FastAPI WebSocket, and an **ARC review tab**. The stack is Next.js (chat UI + AI
SDK agent route) → FastAPI (`api/`, thin contract wrappers + WS) → existing
`capture.*` / `batch.arc.*`. It deliberately reintroduces the previously deferred
thin FastAPI + WebSocket (`docs/decisions.md` "Real-Time Delivery";
`docs/ui-integration.md` §0/§2/§4), but **staged by capability status**: this spec
describes the eventual system, while the first milestone ships only a safe visual
shell plus a read/create boundary. Capabilities that touch unsettled backend areas
(capture process ownership, ARC-before-`watermark_verified`, real authentication)
are marked `blocked` and are non-executable until that work lands.

## Scope

Covers the FastAPI HTTP endpoint contract, the WebSocket message schema, the agent
tool registry, the operator-feedback contract, and the tenancy/authorization model
at the **TB-004** client→API boundary, across all milestones — with a **Capability
Status** matrix marking what is live vs scaffolded vs blocked per milestone. The
binding architectural rule (PAT-010) is that the API **wraps** the existing backend
contracts (`docs/ui-integration.md` §1): it never duplicates their logic, and any
direct SQL it issues runs through a **read-only DB role**. Tenant context
(`sponsor_id`, `site_id`) is owned and injected by the server from a named
`settings.*` value, never supplied by the client or the model.

Does NOT cover: frontend visual design / styling, ARC algorithm internals (owned by
`arc-processor` / `arc-windows`), capture internals (owned by `forwarder` /
`session-init` / `session-close`), hardware LSL sources, or multi-tenant
authentication design (deferred — see OQ-001).

## Data flow

```
Browser  →  Next.js agent route (AI SDK, pinned tools)  →  FastAPI (api/)  →  backend contracts
                                                              │
                                  TB-004: owns tenant context + authorization,
                                          validates every argument (human- or model-supplied)
```

The model emits tool calls only; it never supplies `sponsor_id`, raw SQL, shell
commands, arbitrary endpoint paths, or filesystem paths. The Next.js agent route
forwards tool calls to fixed FastAPI endpoints; **FastAPI is the trust boundary** —
it resolves tenancy from server-side config and validates every argument before
reaching a backend contract, regardless of which tool produced it. Session-derived
text (e.g. ECHO `zone_label`, session metadata) rendered into the agent context is
**data, not instruction**.

## Architecture entries this spec depends on (authored before code)

Added to `.correctless/ARCHITECTURE.md` as part of this spec (RS-005/RS-006):
- **TB-004** — client→API (browser/LLM → FastAPI HTTP+WS).
- **TB-005** — LSL → WS read tap → browser (distinct from TB-002's LSL→DB write path).
- **PAT-010** — API wraps backend contracts (read-only direct SQL; no reimplementation).
- **PAT-011** — capability-status gating (`implemented`/`scaffolded`/`blocked`).

## Capability Status matrix

`implemented` = wired + tested. `scaffolded` = UI surface present (tab/registry
entry) with a documented contract, **but its endpoint is present and returns the
`409` capability-status body — no backend work in M0** (RS-003). `blocked` =
endpoint present, returns `409` capability-status, and a disabled tool. In M0 only
`implemented` endpoints return live data. Capability state is discoverable at
runtime via `GET /capabilities`; the UI sources tool enabled/disabled state from it
and never hardcodes the matrix.

| Capability | Endpoint / tool | Wraps | Status (M0) |
|---|---|---|---|
| Health | `GET /health` | — | implemented |
| Vocab | `GET /vocab` | `VALID_COMPOUNDS` / `VALID_DOSE_UNITS` | implemented |
| List sessions | `GET /sessions` | read-only query | implemented |
| Session status | `GET /sessions/{id}/status` | read-only query (status + watermark events) | implemented |
| Create session | `POST /sessions` | `session_init.workflow.create_session` | implemented |
| Capabilities discovery | `GET /capabilities` | — | implemented |
| Live biosignal tab | `WS /sessions/{id}/stream` | LSL inlet tap | scaffolded (M0: WS upgrade refused w/ reason; tab placeholder) |
| ARC review data | `GET /sessions/{id}/arc` | read persisted `analysis_runs` artifact | implemented (backend read; frontend deferred) |
| Agent tool execution | AI SDK tool registry | — | live for `implemented` capabilities (list/status/create); disabled for `scaffolded`/`blocked` (frontend-shell INV-008a, D-2) |
| Capture start/stop | `capture:start` / `:stop` | watchdog / `ForwarderEngine` | blocked |
| Marker publish | `POST /sessions/{id}/markers` | LSL marker outlet | blocked |
| Close session | `POST /sessions/{id}/close` | `session_close.workflow.run` | blocked |
| ARC run | `arc:run` | `batch.arc.processor.run_arc_post_session` | blocked |

## Endpoint contract

All IDs are UUIDs, validated at the API layer before any DB call (INV-004). Reads
are tenancy-scoped (INV-001). In M0 every non-`implemented` capability endpoint is
**present** and returns the `409` capability-status body **unconditionally and
first**, before any validation, DB connection, or backend call (INV-013); the
scaffolded WebSocket refuses the upgrade with a capability-status close reason.

| Method | Path | Request | Response (200) | Errors | Status (M0) |
|---|---|---|---|---|---|
| GET | `/health` | — | `{status:"ok", version, contract_version}` | — | live |
| GET | `/capabilities` | — | `[{capability, endpoint, status, blocked_reason, gate}]` | — | live |
| GET | `/vocab` | — | `{compounds:[...], dose_units:[...]}` | — | live |
| GET | `/sessions` | — (tenancy server-side) | `{sessions:[{id, status, compound, started_at, closed_at, created_at}...]}` | 503 (DB down) | live |
| GET | `/sessions/{id}/status` | path `id` | `{id, status, started_at, closed_at, watermark_state}` | 404, 422, 503 | live |
| POST | `/sessions` | closed allow-list (below) | `{session_id}` | 422, 503 | live |
| WS | `/sessions/{id}/stream` | path `id` | (deferred; contract below) | upgrade refused (capability close reason) in M0 | scaffolded |
| GET | `/sessions/{id}/arc` | path `id` | persisted artifact envelope (below) | 404, 409 watermark, 422, 503 | live |
| POST | `/sessions/{id}/markers` | — | — | 409 capability-status | blocked |
| POST | `/sessions/{id}/capture:start` / `:stop` | — | — | 409 capability-status | blocked |
| POST | `/sessions/{id}/close` | — | — | 409 capability-status | blocked |
| POST | `/sessions/{id}/arc:run` | — | — | 409 capability-status | blocked |

`sessions` read columns (`id, status, compound, started_at, closed_at, created_at`)
are pinned against `untitledplatform_1a_db/db/SCHEMA.md` (sessions table, migration
002/023) — RS-019.

`watermark_state` (RS-016) is an explicit enum derived from `sessions.status` +
watermark audit events: `not_started | in_progress | verified | failed` — never an
ambiguous `{verified:bool, failed:bool}` pair.

**Capability-status contract (server-side; UI hiding is insufficient).** Every
non-`implemented` capability fails closed with an explicit, structured body so the
operator (and the agent) learns *why* — never a silent no-op or hidden control:

```
409 Capability unavailable
{ "error": "capability_unavailable",
  "capability": "capture_start",
  "status": "blocked" | "scaffolded",
  "blocked_reason": "capture process ownership unsettled",
  "gate": "OQ-004" }
```

The body is returned **first**, before any input validation, DB connection, or
backend call (INV-013). The scaffolded WebSocket cannot return HTTP `409` after the
handshake, so it **refuses the upgrade** with a capability-status close code +
reason carrying the same `capability`/`status`/`blocked_reason`/`gate`.
`GET /capabilities` (implemented) returns the whole matrix
(`[{capability, endpoint, status, blocked_reason, gate}]`) so the UI sources tool
enabled/disabled state at runtime and the agent can report status conversationally.

**`POST /sessions` closed allow-list (RS-004).** The body accepts ONLY an
enumerated field set: `compound`, `capture_source`, `participant_id`,
`compound_dose?`, `compound_dose_unit?`, `protocol_arm?`, and the explicitly named
electrode kwargs (`eeg_reference?`, `eeg_sensor_form?`, `eeg_electrode_system?`,
`eeg_electrode_type?`, `eeg_channel_count?`, `hrv_signal_source?`,
`hrv_electrode_placement?`, `hrv_electrode_type?`, `eda_electrode_placement?`,
`eda_electrode_type?`, `respiration_source?`, … — the full set enumerated in the
implementation, sourced from `session_signal_metadata`). Unknown keys → `422`. The
body MUST NOT contain `site_id` / `sponsor_id`; the server injects them from
`settings.*` (INV-001). The API constructs the `create_session` call from the
allow-list — it never spreads the request body as `**kwargs`.

## WebSocket message schema (`WS /sessions/{id}/stream`) — deferred contract

Documented now; in M0 the WS **refuses the upgrade** with a capability-status close
reason (RS-003). When unblocked, frames are JSON:
- **samples**: `{type:"samples", modality:"eeg"|"hrv"|"eda"|"respiration", channel, t:[lsl_timestamp...], v:[value...]}` — `t` is always `lsl_timestamp` (INV-010).
- **echo**: `{type:"echo", event_type, zone_label, t:lsl_timestamp}`.
- **status**: `{type:"status", state:"connected"|"disconnected"|"reconnecting"|"dropping"}` (RS-020/UX-008).

Boundary TB-005. Bounded ring buffer + per-modality downsample; drop-on-backpressure
with a `drop_count` counter (BND-002). Downsample target rate is OQ-003.

## ARC review contract (`GET /sessions/{id}/arc`)

The backend returns the latest persisted `analysis_runs` artifact, ordered by
`created_at DESC, id DESC`, in this closed envelope:
`{session_id, analysis_id, created_at, provenance:{algorithm_version,
config_sha256, input_sha256, artifact_sha256}, artifact:{...}}`.
`artifact` is the unchanged versioned ARC report generated by the backend CLI,
including its identity, configuration, baselines, signal coverage, events,
quality flags, and safety metadata. The API performs no analysis or writes.

Both the session and analysis query require server-injected sponsor **and** site.
The read-only transaction uses a consistent snapshot. A session must currently
be `closed` and have a `watermark_verified` audit event (INV-006). Errors are:
- Unknown or out-of-scope session: `404 {error:"not_found", message}`.
- Unverified session: `409 {error:"watermark_not_verified", message, watermark_state}`.
- Verified session without persisted analysis: `404 {error:"analysis_not_found", message}`.
- Invalid session UUID: structured `422`; absent tenancy/read-only URL or
  unavailable database: structured `503`.

This activates only the backend read. The frontend implementation is deferred;
capture, marker, close, and ARC execution endpoints retain their existing gates.

## Agent tool registry

The agent acts only through this fixed registry, but **the security boundary is
FastAPI, not the registry** (RS-007/INV-012): the server exposes exactly these
endpoints, 404s unknown paths, and validates every argument identically whether
human- or model-supplied. The registry status flag is UX. No tool accepts
`sponsor_id`, `site_id`, SQL, shell, an endpoint path, or a filesystem path
(PRH-006, BND-003).

| Tool | Maps to | Args (client-supplied) | Status |
|---|---|---|---|
| `list_sessions` | `GET /sessions` | — | scaffolded* |
| `session_status` | `GET /sessions/{id}/status` | `session_id` | scaffolded* |
| `create_session` | `POST /sessions` | allow-listed session fields (no tenancy) | scaffolded* |
| `view_live_signals` | client tab nav | `session_id` | scaffolded |
| `view_arc` | `GET /sessions/{id}/arc` | `session_id` | backend implemented; frontend deferred |
| `start_capture` / `stop_capture` | capture endpoints | `session_id` | blocked |
| `log_marker` | markers endpoint | `session_id`, `event_type`, `zone_label` | blocked |
| `close_session` | close endpoint | `session_id` | blocked |
| `run_arc` | arc:run | `session_id` | blocked |

*M0 (reconciled by frontend-shell, D-2): the registry is visible and agent tool
**execution is live for the three `implemented` capabilities** (`list_sessions`,
`session_status`, `create_session`); execution is disabled (gated 409, reported
conversationally) for every `scaffolded`/`blocked` capability. The in-app registry
and tab placeholders are delivered in `web/`, not `api/`.

## Invariants

### INV-001: Tenancy server-injected; in M0 a correctness scaffold, not access control
- **Type**: must
- **Category**: security
- **Statement**: Tenant context (`sponsor_id`, `site_id`) is injected by the server from a named `settings.*` value (never from the request body/query or a model tool arg); every tenancy-scoped read filters by it; and no wrapped backend contract is ever called with `sponsor_id=None`. **In M0 this is a correctness scaffold for the future multi-tenant model — with no auth (EA-001) and one `.env` sponsor (EA-003) it provides no isolation and must not be cited to justify unblocking write/exec capabilities.**
- **Boundary**: TB-003, TB-004
- **Violated when**: an endpoint accepts `sponsor_id`/`site_id` from the request, a wrapped contract is invoked with `sponsor_id=None`, or a read omits the server tenancy filter.
- **Enforcement**: tenancy resolved in `api/deps.py` from `settings.*`; CI test asserts (a) body-supplied `sponsor_id`/`site_id` is rejected/ignored, (b) the resolved sponsor is non-null before any wrapped call.
- **Guards against**: AP-001
- **Test approach**: integration

### INV-002: API wraps backend contracts; direct SQL runs on a read-only DB role
- **Type**: must
- **Category**: data-integrity
- **Statement**: All writes go through existing contracts (`session_init.workflow`, `ForwarderEngine`, `session_close.workflow`, `batch.arc.processor`); the API's direct-SQL path connects as a **read-only Postgres role** (`GRANT SELECT`-only) so any write raises `InsufficientPrivilege` at the driver. SQL lives in module-level constants (PAT-003), each matching `^(SELECT|WITH)` with no write token. No `SessionRepository` abstraction. (PAT-010)
- **Boundary**: PAT-010
- **Violated when**: `api/` writes/DDLs via any path, reimplements a workflow, or its direct-SQL role can write.
- **Enforcement**: read-only DB role (structural); CI test that a write on the API role raises `InsufficientPrivilege`; closed-SQL-constant positive scan; grep is a lint backstop only.
- **Test approach**: integration

### INV-003: Markers publish to the LSL outlet, never insert echo_events
- **Type**: must
- **Category**: functional
- **Statement**: Context markers are published to the LSL marker outlet (as `capture/marker_simulator.py`); the API never inserts `echo_events`.
- **Boundary**: TB-002
- **Violated when**: any `api/` path inserts `echo_events`.
- **Enforcement**: read-only DB role makes the insert impossible (INV-002); closed-SQL scan as backstop; capability blocked in M0.
- **Test approach**: unit

### INV-004: All inputs validated fail-closed; POST /sessions is a closed allow-list
- **Type**: must
- **Category**: security
- **Statement**: Path/query IDs are validated as UUIDs before use; `POST /sessions` accepts only the enumerated allow-list (unknown keys → 422); enums/ranges validated against closed sets; any client-supplied filesystem path (e.g. future `xdf_path`) is validated against an allowed root with no traversal, or derived server-side. Invalid input → `422` (HTTP) / close (WS) with **no DB call**.
- **Boundary**: TB-004
- **Violated when**: a malformed ID/enum/path reaches a DB query or backend call, or an unknown body key is forwarded into `create_session`.
- **Enforcement**: FastAPI validation dependency runs before the route body; CI test asserts 422 + DB-connection mock not-called; unknown-key test; SQL-injection string in a path id is rejected at validation.
- **Guards against**: AP-001
- **Test approach**: integration

### INV-005: No PII — closed response-field allowlist + UUID participant_id
- **Type**: must-not
- **Category**: security
- **Statement**: API responses serialize only fields on a closed allowlist (Pydantic `response_model` with `extra="forbid"`); `participant_id` is validated as a UUID at the API layer before reaching `create_session`; no PII is collected, returned, logged, or exported. The PAT-001 logger blocklist is a backstop, not the control. Surfaces outside the response-allowlist + blocklist are code-review-only.
- **Boundary**: TB-004
- **Violated when**: an unlisted field serializes out, `participant_id` is non-UUID, or PII appears in a response/log/export.
- **Enforcement**: response-model `extra="forbid"` (structural); CI test over response schemas vs allowlist + a logger-blocklist test; UUID validation at the API layer.
- **Test approach**: unit

### INV-006: ARC endpoints gate on an explicit watermark check, performed in api/ first
- **Type**: must
- **Category**: security
- **Statement**: The ARC read endpoint first queries `sessions.status` and the watermark audit events in `api/` with non-null server sponsor and site. It returns `409` unless the current status is `closed` and the watermark is verified, then reads only the persisted artifact. It does not execute ARC. ARC execution remains unconditionally blocked under INV-013.
- **Boundary**: TB-003
- **Violated when**: an ARC endpoint enters `assert_arc_temporal_alignment` / `run_arc_post_session` for a non-verified session, or calls them with `sponsor_id=None`.
- **Enforcement**: explicit status+watermark gate precondition in `api/`; CI test asserts 409 before-watermark AND that the ARC functions are not entered (patch + assert-not-called).
- **Guards against**: triggering batch work before watermark (AGENTS.md non-negotiable)
- **Test approach**: integration

### INV-007: create_session validation surfaces as structured 422 [integration]
- **Type**: must
- **Category**: parity
- **Statement**: `POST /sessions` surfaces `create_session`'s pre-DB `ValueError`s as HTTP `422` with a structured body `{field, message, valid_choices?}` (for enum fields, `valid_choices` equals the relevant `VALID_COMPOUNDS` / `VALID_DOSE_UNITS` set); vocab is sourced from those sets (no duplicated choice sets in `api/`).
- **Enforcement**: CI integration test (TestClient) exercising real `create_session` validation.
- **Violated when**: invalid compound/dose-unit returns 500, the 422 body is an unstructured string, or `api/` hardcodes a choice set.
- **Test approach**: integration
- **Integration contract**:
  - Entry: FastAPI `TestClient(app)` — real app, route, dependency chain.
  - Through: the create route and `create_session` validation must be exercised; `create_session` validation must NOT be mocked.
  - Exit: status 422; body is `{field, message, valid_choices?}` naming the invalid field; `valid_choices` for `compound`/`dose_unit` equal `VALID_COMPOUNDS`/`VALID_DOSE_UNITS`.

### INV-008: WS tap owns its own resources (split M0 / deferred)
- **Type**: must
- **Category**: resource-lifecycle
- **Boundary**: TB-005 (cites PAT-009)
- **INV-008a (M0, testable now)**: the `WS /sessions/{id}/stream` route exists and **refuses the upgrade with a capability-status close reason** in M0; the WS tap module does not import or accept a `StreamThread` (or its `inlet`/`conn`). Enforcement: CI test asserts upgrade-refused + capability close reason + import check.
- **INV-008b (deferred to the tap milestone, re-typed `must` then)**: the tap opens its own LSL inlets and closes them on client disconnect; `tap.inlet is not forwarder.inlet`; no leak. Enforcement: integration test (`websocket_connect`, stub inlet `.close()` spy, assert close-once on disconnect).
- **Violated when**: the tap shares/mutates forwarder inlets/conn, or leaks inlets.
- **Test approach**: integration

### INV-009: capture:start/stop process lifecycle (blocked in M0)
- **Type**: must
- **Category**: concurrency
- **Statement**: `capture:start` / `:stop` manage the watchdog / `ForwarderEngine`; clean stop uses the watchdog's **platform stop mechanism** (SIGTERM on POSIX, CTRL_BREAK/SIGBREAK on Windows — EA-005), not a bare cross-process SIGTERM; start rejects a double-start for an already-active session. In M0 the endpoints return the `409` capability-status body and spawn no process.
- **Violated when**: stop hard-kills, start double-spawns, or (M0) a process is spawned.
- **Enforcement**: M0 — CI test asserts `409` capability-status + no process spawned. Post-OQ-004 — assert the platform stop signal to the supervised PID; double-start rejected.
- **Test approach**: integration

### INV-010: WS frames use lsl_timestamp as the time axis [unit]
- **Type**: must
- **Category**: data-integrity
- **Boundary**: TB-005 (PAT-004)
- **Statement**: A pure `build_sample_frame(rows) -> dict` maps `lsl_timestamp` (never `db_insert_time` or a server clock) into the frame `t`.
- **Enforcement**: unit test feeds a row with `lsl_timestamp=100.0` and a distinct `db_insert_time`; asserts `frame["t"] == [100.0]` and no value equals `db_insert_time`. (Testable now via the pure builder even before the live tap.)
- **Violated when**: `t` derives from `db_insert_time`/server clock.
- **Test approach**: unit

### INV-011: Backend behavior from config/settings.py
- **Type**: must
- **Category**: functional
- **Boundary**: TB-001
- **Statement**: The API/WS read backend behavior (LSL stream names, vocab, thresholds, tenancy values) from `config/settings.py`; no parallel UI config store. (`NEXT_PUBLIC_*` is a JS build-time client var and is exempt — it is not backend behavior; see Upgrade/Install.)
- **Enforcement**: grep `api/` for `os.environ`/`os.getenv` outside config (PAT-002); CI test.
- **Test approach**: unit

### INV-012: FastAPI is the agent trust boundary (split API-side / agent-side)
- **Type**: must
- **Category**: security
- **Boundary**: TB-004
- **INV-012a (API-side, pytest)**: FastAPI exposes exactly the registry's endpoints; unknown paths → 404; every argument is server-validated regardless of which tool produced it; no endpoint accepts a client/model tenant scope. Session-derived text is treated as data, not instruction.
- **INV-012b (agent-side, code-review-enforced in M0)**: the AI SDK tool registry equals the frozen pinned set and no tool's `execute` constructs SQL/URL/shell/path from model input. No pytest harness can prove this; M0 enforces it by code review, and the spec NAMES a future JS harness (e.g. Vitest) to assert `Object.keys(registry)` equals the pinned list. The real control is INV-012a — an unpinned model tool still cannot reach a side effect the server doesn't expose.
- **Enforcement**: INV-012a — endpoint-allowlist CI test (pytest). INV-012b — code review now; JS harness later.
- **Test approach**: integration (012a); code-review (012b)

### INV-013: Blocked/scaffolded capabilities are non-executable — server-side, explicit
- **Type**: must
- **Category**: security
- **Boundary**: TB-004 (PAT-011)
- **Statement**: A `blocked` or M0-`scaffolded` capability endpoint is **present** and returns the structured `409` capability-status body (`{error:"capability_unavailable", capability, status, blocked_reason, gate}`) **unconditionally and first** — before any input validation, DB connection, or backend call — so no side effect or DB read occurs en route to refusing. The scaffolded WebSocket refuses the upgrade with a capability-status close reason. **Hiding buttons/tools in the UI is insufficient**: the Next.js registry status flag is UX only; the load-bearing control is the server response.
- **Violated when**: a blocked/scaffolded endpoint performs work, opens a DB connection, validates input before refusing, is absent (404 with no status), or its safety depends on the client-side flag.
- **Enforcement**: CI test hits each blocked/scaffolded path with a **raw HTTP client (not the agent)**, asserting `409` + the structured capability body AND that no DB connection was opened and the backend contract (`run_arc_post_session`/`ForwarderEngine`/`session_close.workflow.run`) was not called; the WS test asserts the upgrade is refused with a capability close reason.
- **Guards against**: an agent or any local process invoking unfinished capture/ARC paths
- **Test approach**: integration

### INV-014: Every fail-closed outcome maps to an actionable operator message
- **Type**: must
- **Category**: usability
- **Boundary**: TB-004
- **Statement**: Every fail-closed outcome at the client→API boundary maps to a defined, actionable operator-facing message — never a blank panel, raw status code, raw stack, or silent no-op. Specifically: `422` → inline field error with `valid_choices`, preserving other entered form values; `404` → named reason; `409` capability-status / disabled tool / WS upgrade-refused → message derived from the server body's `blocked_reason` + `gate` (e.g. "Capture start is unavailable — capture process ownership unsettled (OQ-004)"); `409` watermark-gate (ARC) → "ARC unavailable until watermark verified; current state: …"; WS `disconnected`/`dropping` → visible indicator + reconnect affordance; empty `GET /sessions` → "no sessions yet" CTA distinct from an error; backend unreachable (`/health` fails) → global "backend unavailable" banner; local model unreachable/unset (`AGENT_BASE_URL` — frontend-shell INV-007) → chat banner "agent unavailable; read/create still work"; scaffolded tabs render a placeholder stating status + reason. Tool enabled/disabled state and the capability messages are sourced from `GET /capabilities` at runtime (never hardcoded). The agent must answer any actionable request for a `blocked`/`scaffolded` capability with its status message, never a silent no-op. Create-form choices are sourced from `/vocab` up front.
- **Violated when**: any enumerated outcome renders bare or silent, or a 422 wipes the form.
- **Enforcement**: the spec enumerates each status→message mapping; CI/JS test asserts the client renders the mapped copy (mapping table testable; rendering is JS-harness/code-review).
- **Test approach**: integration (mapping) / code-review (rendering)

### INV-015: New UI env vars are optional; settings.validate() is unaffected for non-UI users
- **Type**: must
- **Category**: upgrade-compatibility
- **Statement**: Python-side UI vars (`API_READONLY_DATABASE_URL`, `API_SPONSOR_ID`, `API_SITE_ID`) are optional in `config/settings.py` (`_get_optional`, never `_require`); their absence must not raise in `settings.validate()`, so the existing capture/ARC paths import and validate unchanged. The agent/UI's own vars (`API_BASE_URL`, `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY`, `NEXT_PUBLIC_API_URL`) live only in the JS env, not in `settings` (frontend-shell INV-009). `ANTHROPIC_API_KEY` and the Python-side `API_BASE_URL` were removed in the frontend-shell reconciliation (provider-neutral local routing).
- **Violated when**: a new UI var is required in `settings.validate()`, breaking the capture path for operators who don't run the UI.
- **Enforcement**: CI test runs `settings.validate()` with the UI vars unset and asserts no error.
- **Test approach**: unit

## Prohibitions

### PRH-001: Never write audit_events
- Statement: `api/` never inserts into `audit_events` (trigger-owned).
- Detection: read-only DB role (write raises); closed-SQL scan; CI test.
- Consequence: corrupts the trigger-owned audit trail.

### PRH-002: Never insert echo_events directly
- Statement: markers go through the LSL outlet; `api/` never inserts `echo_events`.
- Detection: read-only DB role; closed-SQL scan.
- Consequence: XDF stops being the recovery source of truth.

### PRH-003: No string-interpolated IDs in SQL (PAT-003)
- Statement: all IDs reach SQL as bound `%(name)s` params, never f-string/concat/`.format`/bare `%`.
- Detection: closed-SQL-constant positive scan; injection-string test (rejected at INV-004 validation).
- Consequence: SQL injection (AP-001).

### PRH-004: Never trigger ARC before watermark_verified
- Statement: no ARC run/read on a non-`verified` session.
- Detection: integration test (INV-006).
- Consequence: batch on incomplete data; AGENTS.md non-negotiable.

### PRH-005: No PII collected/returned/logged
- Statement: no PII anywhere in the surface (bounded by INV-005's allowlist).
- Detection: response-allowlist test + logger-blocklist test.
- Consequence: privacy violation.

### PRH-006: Agent tools cannot supply SQL/shell/endpoint-path/filesystem-path/sponsor_id
- Statement: no tool argument is SQL, shell, an endpoint path, a filesystem path, or a tenant scope.
- Detection: tool arg-schema (server-mirrored) test; INV-004 validation.
- Consequence: prompt injection escalates to arbitrary backend action.

### PRH-007: Blocked/scaffolded capabilities perform no side effect
- Statement: a `blocked`/`scaffolded` capability performs no real side effect and opens no DB connection (INV-013).
- Detection: raw-HTTP CI test (`409` capability-status + no-DB + backend-not-called).
- Consequence: unfinished backend paths run unguarded.

## Boundary Conditions

### BND-001: HTTP/WS request input (TB-004, untrusted)
- Input from: browser / agent-route HTTP + WS bodies and params.
- Validation: UUIDs well-formed; `POST /sessions` closed allow-list (unknown keys 422); enums in closed sets; numeric ranges sane; filesystem paths (future) constrained to an allowed root, no traversal.
- Failure mode: fail-closed — `422` (HTTP) / close (WS), no DB call.

### BND-002: LSL data into the WS (TB-005)
- Input from: LSL inlets the tap owns.
- Validation: fixed-capacity ring buffer; per-modality downsample; drop oldest on backpressure, increment `drop_count`.
- Failure mode: drop frames / close WS — never grow memory unbounded.

### BND-003: Agent tool arguments (LLM-generated, TB-004)
- Input from: model-emitted tool calls.
- Validation: validated against the same server schema as the direct API; `sponsor_id`/`site_id` server-injected, never from the model; session-derived text is data, not instruction.
- Failure mode: fail-closed — reject the tool call.

### BND-004: Request/connection volume (TB-004, DoS — RS-018)
- Input from: repeated `POST /sessions` (no pooling, ui-integration §2) and WS connections.
- Validation: cap concurrent DB connections (reject with `503`, not 500, on exhaustion); cap WS connections per host.
- Failure mode: fail-closed `503`. If caps are deferred, the spec must state the connection-exhaustion DoS as an explicitly accepted M0 risk rather than implying full mitigation.

## STRIDE Analysis

### STRIDE for TB-004 (client→API HTTP/WS)
- Spoofing: no auth in M0 — mitigated only by localhost bind + client co-location (EA-001); real auth required before unblocking write/exec (OQ-001).
- Tampering: input validation (BND-001) + read-only DB role (INV-002) + parameterized SQL (PRH-003).
- Repudiation: backend writes still flow through trigger-audited contracts.
- Information disclosure: response-field allowlist + no PII (INV-005); tenancy filter (INV-001, scaffold only in M0).
- DoS: connection/WS caps or accepted-risk (BND-004); WS backpressure (BND-002); blocked/scaffolded endpoints are `409` capability-status stubs (INV-013).
- Elevation of privilege: FastAPI is the boundary (INV-012a); blocked/scaffolded endpoints return `409` capability-status server-side first (INV-013); no model-supplied tenancy/paths (BND-003/PRH-006).

### STRIDE for TB-003 (tenant-scoped reads)
- Information disclosure: reads filter by non-null server `sponsor_id` and `site_id` (INV-001/INV-006). M0 has one configured tenant and no user authentication.

### STRIDE for TB-005 (LSL → WS read tap → browser)
- Tampering / DoS: bounded buffer + drop-on-backpressure (BND-002); tap owns its inlets and never holds a `StreamThread`/its resources (INV-008, PAT-009); markers publish via the outlet only (INV-003, TB-002).

## Environment Assumptions

- **EA-001**: localhost-bound, **client co-located on the same host**; localhost tenancy is not authentication — exposure beyond localhost requires real auth before unblocking any write/exec capability (OQ-001).
- **EA-002**: LSL streams resolvable on the local network (as the forwarder assumes).
- **EA-003**: one sponsor/site context per local deployment, from a named `settings.*` var; no per-request principal in M0 — INV-001's security value is vacuous until OQ-001.
- **EA-004**: The agent route is provider-neutral, running server-side in `web/` and routing to a local OpenAI-compatible model via a LiteLLM proxy keyed on `AGENT_BASE_URL`/`AGENT_MODEL` (JS env, not Python settings). Absence/unreachability disables only the agent route, not the read/create API or read tabs (INV-015; frontend-shell INV-007/EA-003). The egress target is loopback/private only (frontend-shell INV-013) — this supersedes any earlier "outbound HTTPS to the model provider" framing.
- **EA-005**: clean-stop for capture is the watchdog's platform stop mechanism (SIGTERM POSIX / CTRL_BREAK/SIGBREAK Windows); dev platform is Windows.
- **EA-006**: a second concurrent LSL inlet (the WS tap) must be **validated** not to perturb the forwarder's chunk timing / clock-offset before INV-008b is unblocked — asserted, not assumed.
- **EA-007**: the agent/UI surface requires a separate, declared Node.js + pnpm + Next.js + AI SDK + uPlot toolchain alongside Python/`uv`.
- **EA-008**: the agent route requires outbound HTTPS to the model provider; the read/create API and the WS tap do not.

## Upgrade / Install Requirements (RS-011)

- New Python deps (`fastapi`, `uvicorn`, `websockets`) added to `pyproject.toml` `[project.dependencies]`; `uv.lock` regenerated; CI `uv sync --frozen` stays green.
- `api/` added to `[tool.hatch.build.targets.wheel].packages` (the list is hardcoded) and to the bandit pre-commit scan scope.
- New UI env vars added to `.env.example` with comments; Python-side vars optional (INV-015); `NEXT_PUBLIC_*` documented as JS-env-only.
- `.gitignore` covers `web/node_modules/`, `web/.next/`, `web/.env.local`; a committable `web/.env.example` template survives the env-commit guard.
- CI gains a JS lane (`pnpm install`, `next build`, JS lint/test); the Correctless `build` command is non-empty before `web/` is considered shippable.
- Graceful degradation: UI shows a clear state when FastAPI is unreachable, DB is down (`503`), LSL streams are absent, or a verified session has no ARC output (`{ecps:[]}`).

## Milestone Gates

M0 ships **localhost-only, read/scaffold-focused, with no write or execution
capability enabled**. A capability moves from `blocked`/`scaffolded` to
`implemented` only when its gate below is fully specified. Until then it is served
via the capability-status contract (`409` / WS upgrade-refused), not hidden.

- **M1 entry gate — OQ-001 (Auth)**: no write/exec capability is enabled until BOTH
  an **authentication** model AND a **tenant-authorization** model are specified.
  INV-001 tenancy remains a correctness scaffold, not access control (EA-001/EA-003),
  and must not be cited to justify unblocking.
- **M1 entry gate — OQ-004 (Capture process model)**: `capture:start/stop` and the
  start/stop tools stay disabled until the spec covers **watchdog subprocess
  ownership, duplicate-start prevention, graceful shutdown, restart, and orphan
  recovery** (composing with EA-005 platform-signal semantics).

## Open Questions

- **OQ-001 (M1 entry gate)**: API authentication + tenant-authorization for 1a — localhost-only + `.env` tenancy, or a login/identity model? Required deliverables: an authentication model AND a tenant-authorization model. No write/exec capability is enabled until both are specified. Does not block M0.
- **OQ-003**: WS per-modality downsample target rate for uPlot — pin defaults in `config/settings.py`. (Gates the tap milestone.)
- **OQ-004 (M1 entry gate)**: `capture:start` process model under FastAPI — watchdog subprocess vs in-process `ForwarderEngine`. Required deliverables: subprocess ownership, duplicate-start prevention, graceful shutdown, restart, and orphan recovery. Gates INV-009 unblock (M1).
- **OQ-002 (resolved)**: the agent obtains tenancy from a server-injected named `settings.*` value, never a tool arg (INV-001/BND-003).
- **OQ-005 (resolved)**: TB-004, TB-005, PAT-010, PAT-011 are authored in ARCHITECTURE.md before M0 code.
