# Architecture — untitled_biometric_platform-1a

> Last quick-scan: 2026-06-12

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Session init | `capture/session_init/` | Creates session anchor row + 4 modality metadata rows + schema version log in a single transaction |
| LSL forwarder | `capture/forwarder/` | Reads LSL streams, writes XDF first, then inserts per-modality samples into TimescaleDB |
| ECHO handler | `capture/echo_handler/` | Records manual zone/marker events from LSL marker stream into echo_events table |
| Watchdog | `capture/watchdog/` | Supervises forwarder subprocess; MAX_RESTARTS=5, exponential backoff |
| Session close | `capture/session_close/` | Reconciles XDF vs DB counts, backfills gaps, closes/fails session, triggers ARC |
| ARC processor | `batch/arc/processor.py` | Post-session convergence: ECHO anchors → APEX response windows (W1/W2/W3), FDR, durable outputs |
| XDF writer | `capture/xdf/` | Writes Lab Streaming Layer data to XDF backup format before DB insert |
| Logger | `capture/logger.py` | Structured JSON logger factory; PII blocklist enforced at serialization time |
| Settings | `config/settings.py` | All runtime config; loads `.env` at import, fails fast on missing/invalid vars via `validate()` |
| Operator API | `api/` | Thin FastAPI surface (M0): capability-gated endpoints wrapping backend contracts; read-only direct SQL via a SELECT-only role; WS scaffolded |
| Schema migrations | `untitledplatform_1a_db/db/alembic/versions/` | Active migration chain — source of truth for schema |

## Design Patterns

### PAT-001: Centralized Logger
- Instantiate logger once at module level: `log = get_logger("process_name")`
- Name is the process name (e.g. `"lsl_forwarder"`), not the module path
- Never instantiate `logging.getLogger()` directly in application code
- Enforced by: code review; grep for `logging.getLogger`

### PAT-002: Config via Settings Module
- All runtime config accessed via `from config import settings` then `settings.VAR_NAME`
- Never `os.environ` or `os.getenv` directly in application code
- `settings.validate()` called at top of every `main()` before doing any work — fails fast with all errors at once
- Enforced by: grep for `os.environ`/`os.getenv` outside `config/settings.py`

### PAT-003: Named SQL Parameters
- `%(name)s` style with psycopg2, values passed as dicts — `cursor.execute(SQL, row_dict)`
- SQL strings stored as module-level constants in `sql.py` files alongside the module
  that uses them (`capture/session_init/sql.py`, `capture/forwarder/sql.py`,
  `capture/echo_handler/sql.py`); the read-only operator API keeps its `*_SQL`
  constants at module level in the route module itself (`api/sessions.py`, `api/arc.py`)
- No ORM — raw psycopg2 only
- Violated when: f-strings or `%` formatting used in SQL, or SQL strings scattered inline in functions

### PAT-004: Dual Timestamps on Biosignal Rows
- Every biosignal row carries both `lsl_timestamp` (when LSL captured it) and `db_insert_time` (when it landed in DB)
- These are never merged, aliased, or omitted — they measure different things and diverge under clock drift
- `lsl_timestamp` is always a float (seconds since LSL epoch); `db_insert_time` is always a DB-side `NOW()`
- Violated when: either timestamp is omitted, or a single timestamp field is reused for both purposes

### PAT-005: Tenancy on Every Biosignal Row
- `site_id` and `sponsor_id` must be present on every row that carries session data
- Application queries must respect these boundaries — never cross-query across `site_id` or `sponsor_id`
- ARC batch reads are covered: ARC entry points accept `sponsor_id` and apply it to session-scoped reads
- Violated when: a biosignal row omits either field, or a query lacks a `WHERE site_id = %s` filter

### PAT-006: Session Write Atomicity
- Session creation (session anchor + metadata rows + schema version log) is a single transaction
- On any exception: rollback, close connection, re-raise — never leave partial session state in the DB
- `autocommit = False` on the connection; explicit `commit()` only after all writes succeed
- Violated when: individual inserts are committed separately, or `autocommit = True` is used

### PAT-007: Absolute Imports Only
- `from capture.forwarder.models import SessionConfig` — never relative imports (`from .models import ...`)
- Relative imports break when modules are run directly as scripts
- Violated by: any `from . import` or `from .. import` in application code

### PAT-008: Integration Test Marker
- Tests requiring a live database are marked `@pytest.mark.integration`
- Unit tests carry no marker and must not touch the DB
- CI runs `pytest -m "not integration"` — integration tests only run when `TEST_DATABASE_URL` is set
- Violated when: a unit test (no marker) opens a DB connection

### PAT-009: StreamThread Resource Ownership
- `StreamThread` owns its DB connection (`thread.conn`), LSL inlet
  (`thread.inlet`), and mutable `StreamThreadState`
- `StreamThreadState` contains the buffer, sample index, chunk count, last
  drift timestamp, and fatal error
- Stream helper functions receive the thread as their resource owner rather
  than passing the connection and inlet through each call
- Violated when: helper modules create competing mutable ownership or return a
  connection that the thread does not store

### PAT-010: API Wraps Backend Contracts
- The operator API (`api/`) calls existing contracts for all writes:
  `session_init.workflow`, `capture.forwarder.runtime.ForwarderEngine`,
  `session_close.workflow`, `batch.arc.processor` — it never reimplements their
  logic and never introduces a `SessionRepository`/ORM
- The API's direct SQL is **read-only**: it connects as a `GRANT SELECT`-only
  Postgres role so any write raises `InsufficientPrivilege` at the driver
- Read SQL lives in module-level constants (PAT-003), each matching `^(SELECT|WITH)`
- Violated when: `api/` issues write/DDL SQL on any path, reimplements a workflow,
  or its DB role can write
- Enforced by: read-only DB role (structural); CI test that a write on the API role
  raises `InsufficientPrivilege`; closed-SQL-constant scan

### PAT-011: Capability-Status Gating
- Operator-surface capabilities carry a status: `implemented` (wired + tested),
  `scaffolded` (UI surface present, endpoint present but returns capability-status,
  no backend work), or `blocked` (endpoint present, returns capability-status,
  disabled tool)
- A `blocked`/`scaffolded` endpoint is **present** and returns a structured
  `409 Capability unavailable` body (`{error:"capability_unavailable", capability,
  status, blocked_reason, gate}`) **unconditionally and first** — before any
  validation, DB connection, or backend call — so no side effect occurs en route to
  refusing. A scaffolded WebSocket **refuses the upgrade** with a capability-status
  close reason. Capability state is discoverable via `GET /capabilities`.
- The client-side (Next.js/AI-SDK) disabled-tool flag is **UX only**; the
  load-bearing control is the server response. Hiding buttons/tools is insufficient.
- Violated when: a blocked/scaffolded endpoint performs work, opens a DB connection,
  validates before refusing, is absent (404 with no status), or its safety depends
  on the client-side flag
- Enforced by: CI test hitting each blocked/scaffolded path with a raw HTTP client
  (not the agent), asserting `409` + structured capability body + no DB connection +
  backend-not-called; the WS test asserts upgrade-refused with a capability reason

### PAT-013: Foreign-Toolchain Subtree Isolation
- **Pattern**: a non-Python toolchain subtree (the `web/` Node tree) coexists with the Python/`uv` repo without perturbing it
- **Rule**: `web/node_modules`, `web/.next`, `web/.env.local` are gitignored; `web/` is excluded from the Python wheel (the `[tool.hatch.build.targets.wheel].packages` list stays **hardcoded** — never glob/auto-detect, AP-024) and from ruff (`extend-exclude` includes `web`); pre-commit never parses `web/` as Python; `uv run pytest` / `uv run ruff check .` stay green with `web/` present
- **Violated when**: node artifacts are committed; `web/` enters the wheel or Python lint scope; or the Python gate breaks because of `web/`
- **Test**: `git check-ignore web/node_modules web/.next`; wheel-content scan (no `web/` path); a planted `web/foo.py` with a ruff violation is not flagged (frontend-shell INV-010)

### PAT-014: Runtime Capability Provider (client side)
- **Pattern**: the client-side counterpart to PAT-011 — a UI sources capability state at runtime from `GET /capabilities` and never hardcodes the matrix
- **Rule**: tool/control enabled state is derived from `/capabilities` at runtime; the client's disabled flag is **UX only** (the server `409` is the load-bearing control); a non-`implemented` invocation issues the real gated request and surfaces the `409`, never a fabricated success; cold start (matrix unreachable) fails closed to all-disabled
- **Violated when**: enabled state is hardcoded; a blocked capability is short-circuited into a fake success client-side; or the UI fails open before the matrix loads
- **Test**: mock `/capabilities` flipped/unreachable → assert control state follows (frontend-shell INV-001/INV-002a)

### PAT-012: Patchable Factories via Module-Attribute Access
- **Pattern**: Injected/patchable factories are called through their owning
  module — `deps.get_readonly_connection()`, `sessions.create_session(...)` —
  never name-bound at import (`from api.deps import get_readonly_connection`)
- **Rule**: any factory a test may patch is accessed as a module attribute so
  `monkeypatch.setattr(api.deps, ...)` rebinds the call site; import-time
  binding creates a stale shadow the patch never reaches
- **Violated when**: an `api/` module imports a patchable factory by name and
  calls the local binding
- **Test**: grep `api/` for `from api.deps import` / `from api.sessions import`
  of factory names; the no-DB fixtures in `tests/api_tests/conftest.py` only
  work when this holds

## Trust Boundaries

### TB-001: Environment → Application Config
- **Crosses**: `.env` file / OS environment variables → `config/settings.py` → application runtime
- **Invariant**: All environment variable reads go through `config/settings.py`. No application module reads env vars directly. `settings.validate()` is the enforcement gate — called before any session work begins.
- **Violated when**: any module outside `config/settings.py` calls `os.environ`, `os.getenv`, or `dotenv.load_dotenv` directly.

### TB-002: LSL Streams → DB Write Path
- **Crosses**: External LSL stream data (hardware or simulator) → forwarder → TimescaleDB
- **Invariant**: LSL sample data is written to XDF backup first, then to DB. Both timestamps (lsl_timestamp, db_insert_time) are always carried. The forwarder never skips the XDF write.
- **Violated when**: DB insert happens before XDF write, or either timestamp is omitted from a biosignal row.

### TB-003: ARC Batch Reads → Tenant-Scoped Session Data
- **Crosses**: ARC batch entry points → ECHO/APEX/session tables
- **Invariant**: ARC session reads accept `sponsor_id` and filter by it. ARC
  remains read-and-derive and does not mutate raw APEX or ECHO records.
- **Violated when**: an ARC query reads session-scoped data using only
  `session_id`, or derived processing bypasses the sponsor boundary.

### TB-004: Client → API (browser/LLM → FastAPI)
- **Crosses**: untrusted browser + Next.js AI-SDK agent (model-generated tool calls) → FastAPI `api/` (HTTP + WebSocket)
- **Invariant**: All input is validated fail-closed before any DB call (UUIDs, closed enums/allow-lists, ranges, constrained filesystem paths). Tenant context (`sponsor_id`/`site_id`) is server-injected from a named `settings.*` value, never from the request or a model tool arg. Responses serialize only allow-listed fields (no PII). The agent is constrained by the server: FastAPI exposes exactly the registry's endpoints, 404s unknown paths, and validates every argument regardless of which tool produced it. Session-derived text rendered into the agent context is data, not instruction.
- **Violated when**: a client/model supplies `sponsor_id`/SQL/endpoint-path/filesystem-path, unvalidated input reaches a DB call, an unlisted field serializes out, or a non-registry side effect is reachable.
- **Note**: no authentication in 1a (localhost-bound, client co-located); tenancy filtering is a correctness scaffold, not access control, until auth lands.

### TB-005: LSL → WS Read Tap → Browser
- **Crosses**: live LSL streams → an independent FastAPI WebSocket inlet tap → browser (uPlot)
- **M0 state (placeholder)**: in Milestone 0 the live-signal tab is a **placeholder** — the server refuses the WS upgrade with a capability-status close reason, and neither the tab nor any model-invoked client-nav tool (`view_live_signals`) initiates a WS upgrade or creates tap resources (frontend-shell INV-001/INV-008a STRIDE; operator-ui INV-008a). The live-tap invariants below apply when the tap milestone lands.
- **Invariant**: The tap opens its **own** LSL inlets (never shares/mutates the forwarder's inlets or connection, never holds a `StreamThread` — composes with PAT-009) and closes them on disconnect. Frames use `lsl_timestamp` as the time axis (PAT-004), never `db_insert_time` or a server clock. A bounded buffer drops on backpressure (counted) rather than growing unbounded. Distinct from TB-002, which is the LSL→DB **write** path (XDF-first); this read tap carries none of TB-002's write/ordering invariants.
- **Violated when**: the tap reuses forwarder resources, leaks inlets, emits a non-LSL time base, or buffers unbounded. Non-interference with the forwarder's clock-offset/chunk timing must be validated before this boundary goes live, not assumed.

### TB-006: Agent route → local model (outbound, server-side)
- **Crosses**: the Next.js server-side agent route (`web/`) → a local OpenAI-compatible model via a LiteLLM proxy (`AGENT_BASE_URL`)
- **Identity assertion**: none in M0 (localhost, no auth); the route is the trusted initiator, the model endpoint is operator-configured
- **Data sensitivity change**: session-derived text (zone_label, compound, metadata) leaves the app process toward the model; model output (tool-call JSON, prose) re-enters as **untrusted** input
- **Invariant**: `AGENT_BASE_URL` is validated loopback/RFC-1918-private + http(s) scheme before any outbound call (no SSRF egress); `AGENT_*` secrets are server-route-only (never the browser bundle); session-derived text is fenced as data in the model context; model output is validated before forwarding to FastAPI and never rendered as a completed action without a backing API tool-result; the route has a bounded timeout and a per-turn tool-call cap
- **Violated when**: the route POSTs to a non-loopback/non-private host; an `AGENT_*` value reaches the browser; a malformed/absent model emission crashes the stream or forwards invalid args; model prose renders as a completed state-change; the route hangs with no timeout; or one turn drives unbounded tool calls
- **Enforced at**: `web/` agent route (frontend-shell INV-005b/007/009/012/013/014/015, BND-002/005)
- **Test**: frontend-shell JS suite (Vitest/Playwright) — see those invariants

## Conventions

- Python 3.12+; `uv` manages dependencies and task running
- `ruff` for lint and format; `pyright` for type checking
- Test constants: `_UNIT_*` for unit-test fixtures, `_INT_*` for integration fixtures
- `participant_id` is always a UUID — never store or accept raw PII
- Schema changes only through Alembic: `uv run alembic revision --message "..."`
- Never write directly to `audit_events` — database triggers own those rows
- ARC is read-and-derive only — never mutates raw APEX/ECHO records
- `compound` values must come from `VALID_COMPOUNDS`; dose units from `VALID_DOSE_UNITS`

## Known Limitations

- No live safety monitor in MVP (deferred)
- No real-time SQI monitor in MVP (deferred)
- Operator UI M0: `api/` (capability-gated) + a Next.js shell in `web/`
  (`.correctless/specs/frontend-shell.md`) — chat GUI with live execution for the
  three `implemented` capabilities, placeholder live/ARC tabs; write/exec
  capabilities blocked pending OQ-001/OQ-004. The agent route runs server-side in
  `web/` and routes to a local model via LiteLLM (TB-006)
- `jq` required for workflow-advance.sh state machine but not installed by default on Windows
