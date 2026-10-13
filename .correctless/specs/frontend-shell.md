# Spec: Operator UI — Frontend Shell (Next.js, M0)

## Metadata
- **Created**: 2026-06-13T06:11:26Z
- **Reviewed**: 2026-06-13 (creview-spec, 6-agent adversarial + self-assessment; 19 findings RS-001..019, all accepted/incorporated)
- **Status**: reviewed
- **Impacts**: operator-ui (narrows M0 agent-execution wording → D-2; generalizes/relocates EA-004 + removes ANTHROPIC_API_KEY; reconciles INV-014 copy)
- **Branch**: feature/frontend-shell
- **Research**: null (versions pinned at install; AI SDK major pinned per OQ-001)
- **Recommended-intensity**: high
- **Intensity**: high
- **Intensity reason**: keyword signal (session, injection); TB refs (TB-004, TB-005, TB-006); composes with the HIGH-intensity operator-ui contract
- **Override**: none

## Context

The operator-ui API surface (`api/`, M0) landed with no client. This feature builds the
**frontend shell**: a runnable Next.js (App Router) app in `web/` that an operator opens on
localhost and uses to drive the backend through the existing FastAPI contracts. It ships a
Vercel AI SDK **chat GUI** whose server-side agent route talks to a **local, OpenAI-compatible
model via a LiteLLM proxy** (provider-agnostic, per the repo's "Local Model Agent Neutrality"
decision), a pinned **tool registry** that executes the three *implemented* capabilities for
real and gates the rest, plus placeholder **live-signal and ARC tabs**. The shell is the
*less-trusted client side* of TB-004 and the *initiator* of the new TB-006 (agent route →
local model) — FastAPI remains the security boundary; the UI mirrors capability state but never
owns enforcement.

## Scope

**Covers:** the Next.js App Router app in `web/`; the typed API client over the `api/` HTTP
contract; the AI SDK chat UI + server-side agent route to a local LiteLLM proxy; the pinned
agent tool registry and arg schemas; capability-driven enable/disable sourced at runtime from
`GET /capabilities`; fail-closed rendering of every API outcome (409/503/422/404) plus in-flight
and empty states; session-derived-text handling (data, not instruction); the agent-route
trust boundary (timeout, SSRF egress control, loop cap, malformed-emission handling); the
frontend test strategy (Vitest + React Testing Library + Playwright) wired as an enforced gate;
and the env/packaging boundary between the Node tree and the Python toolchain.

**Composition & reconciliation (operator-ui — review-gated edits, hard prerequisites):**
1. Narrow operator-ui's "agent tool execution — disabled globally (M0)" to **"execution disabled
   for non-`implemented` capabilities"** (resolves verification drift **D-2**). INV-008a here is
   the contract.
2. The in-app tab placeholders / visible tool registry promised by operator-ui's M0 matrix are
   delivered **here in `web/`**, not in `api/`.
3. **Remove `ANTHROPIC_API_KEY`** from `config/settings.py` and `.env.example`; generalize/relocate
   operator-ui **EA-004** and the **INV-014** "agent unavailable" copy to provider-neutral local
   routing keyed on `AGENT_BASE_URL`/`AGENT_MODEL` (LiteLLM). The agent route is **server-side in
   `web/`**, so these vars live in the JS env, not Python settings. The user-gated
   `tests/api_tests/test_settings_optional.py` is regenerated to drop `ANTHROPIC_API_KEY`
   (user-gated per the no-test-edits rule).

**Architecture prerequisites (flagged for `/cupdate-arch`, RS-002/RS-015):** author **TB-006**
(agent route ↔ local model), **PAT-013** (foreign-toolchain subtree isolation — Node tree in a
uv repo), **PAT-014** (client-side runtime capability provider); add an **M0 placeholder clause
to TB-005** (or pin frontend refs to operator-ui INV-008a meanwhile); update the stale
ARCHITECTURE.md "Known Limitations" ("Next.js shell deferred") via `/cdocs`.

**Does NOT cover:** the FastAPI endpoint/WS/registry contracts (operator-ui owns them); visual
design / styling / component library (OQ-002); the live biosignal tap and ARC review surfaces
beyond placeholders (deferred, gated by OQ-003/OQ-001 of operator-ui); authentication /
multi-tenant authorization (operator-ui OQ-001); LiteLLM's own routing config (outside the repo);
unblocking any `blocked`/`scaffolded` backend capability. **Server-side length/charset bounds on
`create_session` free-text fields** and a **CORS/Origin/Host allow-list on the FastAPI surface**
are recorded as follow-on backlog items against `api/`/operator-ui (see Open Questions).

## Complexity Budget
- **Estimated LOC**: ~1000–1500 (app shell, components, agent route, typed API client, tool registry, capability provider, tests)
- **Files touched**: ~30–40 new under `web/`; plus `.env.example`, `config/settings.py` (remove ANTHROPIC_API_KEY), `.gitignore`, `pyproject.toml` (ruff exclude), `.pre-commit-config.yaml` / `.secrets.baseline`, `.correctless/config/workflow-config.json` (JS lane), regenerated `tests/api_tests/test_settings_optional.py` (user-gated), and (review-gated) `operator-ui.md`
- **New abstractions**: typed API client, pinned tool registry, capability context/provider, server-side agent route
- **Trust boundaries touched**: TB-004 (client side), **TB-006 (agent route → local model, new)**, TB-005 (placeholder only in M0)
- **Risk surface delta**: medium-high (new Node tree in a uv repo; new external local-model dependency with an SSRF egress + prompt-injection-into-context surface; a new test-runner gate)

## Invariants

### INV-001: Capability state is sourced at runtime, never hardcoded [integration]
- **Type**: must · **Category**: security · **Boundary**: TB-004, composes with PAT-011 / PAT-014
- **Statement**: Tool/control enabled state is derived at runtime from `GET /capabilities`; the client never hardcodes the matrix. A capability flipped to `blocked`/`scaffolded` renders its control disabled with the server `blocked_reason`/`gate`. **Cold start**: if `/capabilities` is unreachable at first paint, the UI fails closed — all capabilities render disabled until the matrix loads (never fail-open to enabled).
- **Violated when**: enabled state is a hardcoded constant; the UI shows a capability usable when `/capabilities` says otherwise; or a capability defaults to enabled before the matrix loads.
- **Enforcement**: CI test (mock `/capabilities` flipped status → assert control state changes; mock `/capabilities` unreachable → assert all-disabled); grep backstop for a hardcoded matrix.
- **Test approach**: integration

### INV-002a: Gated invocation reaches the server and surfaces the 409 (no client-fabricated success) [integration]
- **Type**: must · **Category**: security · **Boundary**: TB-004, composes with PAT-011 / operator-ui INV-013
- **Statement**: When the tool dispatcher runs `execute(toolName, args)` for a non-`implemented` capability, it issues a real HTTP request to the mapped fixed endpoint and resolves to a structured result carrying the server's `409` `{error, capability, status, blocked_reason, gate}` — never a synthesized `{success:true}`. The client's disabled-control flag is presentation only.
- **Violated when**: a blocked/scaffolded invocation is short-circuited client-side into a fake success, or safety depends on the disabled flag.
- **Enforcement**: CI test with a stubbed transport — assert exactly one request to the fixed path and the returned object's `status` is `blocked`/`scaffolded`, not a fabricated success.
- **Test approach**: integration

### INV-002b: Agent prompt instructs tool-calling over narration (model-behavior; review/eval only)
- **Type**: must · **Category**: security · **Boundary**: TB-006 · **Enforcement**: code review of the system prompt + an offline eval set — **NOT covered by the unit gate**. Stated explicitly so reviewers do not assume INV-002a closes PRH-004's model-fabrication half.
- **Statement**: The system prompt instructs the model to act through tools and report tool results, never to narrate state-changing outcomes it did not perform.
- **Test approach**: (eval/review)

### INV-003: The agent tool registry is a fixed, closed set with typed, bounded args
- **Type**: must · **Category**: security · **Boundary**: TB-004 (LLM-generated args), composes with operator-ui INV-012 / PRH-006
- **Statement**: The agent acts only through a fixed enumerated registry. Each tool's arg schema is `.strict()`/extra-forbid: `session_id` is a UUID; `create_session` accepts only the operator-ui allow-list fields; free-text fields (e.g. `protocol_arm`, `room_id`) carry a max-length bound (defense-in-depth against stored-injection, RS-010). No tool accepts any key in `BANNED_ARG_KEYS = {sponsor_id, site_id, sql, query, url, endpoint, path, cmd, shell}`. Each tool's target endpoint is a compile-time constant string, never derived from an arg.
- **Violated when**: the registry is open/dynamic; a schema admits a banned key or an unbounded free-text field; or a tool endpoint is model-supplied.
- **Enforcement**: agent tool-pinning (closed registry constant) + CI unit tests: `Object.keys(registry)` equals the pinned list; each schema rejects every `BANNED_ARG_KEYS` entry, a non-UUID `session_id`, and an over-length free-text value; endpoint is a constant.
- **Test approach**: unit

### INV-004: Neither the client nor the Node agent route sends tenant scope to the API
- **Type**: must-not · **Category**: security · **Boundary**: TB-004, composes with TB-003 (client-side complement of server tenant-injection)
- **Statement**: No request originating in `web/` — browser client **or** the server-side agent route — includes `sponsor_id`/`site_id` in body, query, or header. Tenancy is injected server-side (operator-ui INV-001). The create form exposes no tenancy inputs. The Node route must not read `API_SPONSOR_ID`/`API_SITE_ID` from its env and attach them.
- **Violated when**: any `web/` outbound request (client or route) sets a tenancy key, or a tenancy field appears in a form.
- **Enforcement**: CI test over the API-client layer AND the agent route's outbound calls asserting no tenancy keys; grep backstop.
- **Test approach**: unit

### INV-005a: Session-derived text is DOM-inert across all render paths [integration]
- **Type**: must · **Category**: security · **Boundary**: TB-004 (DOM)
- **Statement**: Text originating from session data or API responses — `zone_label`, `compound`, session metadata, **the server `409` `blocked_reason`/`gate`, and the `422` `{field, message}` (which can echo operator input via `_map_create_value_error`)** — is rendered as inert escaped text. No `dangerouslySetInnerHTML`/`eval`/`Function` on session-derived strings.
- **Violated when**: any session-derived or echoed-input string renders as HTML/markup or executes — on the chat, lists, tabs, OR error/validation messages.
- **Enforcement**: CI test rendering a session whose `zone_label` AND a 422 message carry a `<script>`/markup payload → assert literal escaped text, no element created; lint/grep ban on `dangerouslySetInnerHTML` for session-derived values.
- **Test approach**: integration

### INV-005b: Session-derived text is fenced as data in the model context (formatting-testable; model-behavior eval-only)
- **Type**: must · **Category**: security · **Boundary**: TB-006
- **Statement**: When session-derived text is composed into the agent request, the route wraps it in pinned untrusted-data delimiters and never concatenates it into the `system` message.
- **Enforcement**: CI test inspects the constructed request payload (data block contains the fence + raw string; `system` does not contain the raw string). **Caveat (stated):** this proves the fence is applied, not that the model honors it — injection-resistance of the model is eval/review only.
- **Test approach**: unit (+ eval/review for model behavior)

### INV-006: Every API outcome maps to an actionable, researcher-legible message [integration]
- **Type**: must · **Category**: functional · **Boundary**: TB-004
- **Statement**: Each outcome renders a specific, **researcher-facing** message — never a raw stack/JSON dump, silent swallow, or verbatim engineering string: `409 capability_unavailable` → a plain-language reason (the raw `gate` ID like `OQ-004` is not shown verbatim; `blocked_reason`/`gate` may be `null` and must render without `"(null)"` or a crash); `503 backend_unavailable` → "backend unavailable, retry"; `503 tenancy_not_configured` → names the `.env` file + example values + doc pointer (not bare "set API_SPONSOR_ID"); `422` → field-level validation `{field, message, valid_choices?}` that **preserves other entered form values**, and when surfaced via the agent path (no form) the agent reports the invalid field + `valid_choices` and offers to retry; `404` → "not found"; **empty `GET /sessions`** → a "no sessions yet" zero-state distinct from an error.
- **Violated when**: any status renders blank/raw/ignored, a `null` field crashes the render, a 422 wipes other inputs, or operator copy is engineering-facing.
- **Enforcement**: CI test mocking each status + the null-field and empty-list cases; assert mapped copy renders, other form values persist, and `not.toMatch(/\{|\}|Traceback/)`.
- **Test approach**: integration

### INV-007: The agent route fails closed within a bounded timeout and degrades independently [integration]
- **Type**: must · **Category**: resource-lifecycle · **Boundary**: TB-006, EA-010
- **Statement**: The agent route returns a structured `{error:'agent_unavailable', reason}` (never throws/hangs) within a bounded timeout under each of: (a) `AGENT_BASE_URL` unset; (b) set but connection-refused; (c) set, connection **accepted, then stalls** past the timeout. The operator message distinguishes *not-configured* vs *unreachable* vs *stalled/crashed*, and states the **model** (not the backend API or their session data) is affected. Meanwhile the session list, status, create form, and capability matrix continue to function.
- **Violated when**: an unreachable/unset/stalled endpoint crashes the app, hangs the UI past the deadline, disables non-chat surfaces, or the message implies session-data loss.
- **Enforcement**: integration test driving all three modes (fake LiteLLM that accepts-then-sleeps for mode c) with fake timers advanced past the configured timeout, asserting the structured outcome before a hard deadline; RTL test asserts chat disabled w/ the right sub-case message AND read/create still interactive.
- **Test approach**: integration

### INV-008a: Live execution only for `implemented` capabilities (dispatcher; testable) [integration]
- **Type**: must · **Category**: functional · **Boundary**: composes with operator-ui agent-registry (D-2)
- **Statement**: With the model layer stubbed to emit a fixed tool call, the dispatcher (a) issues a live `POST /sessions` for `create_session`, (b) returns the structured `409` for `close_session` (and other gated tools) without synthesizing success, and (c) leaves `implemented` tools (`list_sessions`/`session_status`/`create_session`) enabled when `/capabilities` reports them so.
- **Violated when**: a gated tool returns a synthesized success, or an implemented tool is incorrectly gated off.
- **Enforcement**: CI test at the dispatcher seam (model stubbed) asserting the transport calls + the 409 surfacing + the not-gated-off direction.
- **Test approach**: integration

### INV-008b: Model tool-selection correctness (model-behavior; eval/review only)
- **Type**: must · **Category**: functional · **Boundary**: TB-006 · **Enforcement**: offline eval set + code review — **not unit-gated**. Stated so reviewers don't assume INV-008a closes the model-selection half.

### INV-009: Frontend env vars stay in the JS env and never reach the browser bundle
- **Type**: must · **Category**: data-integrity · **Boundary**: TB-004/TB-006, EA-004
- **Statement**: Frontend vars (`API_BASE_URL`, `AGENT_BASE_URL`, `AGENT_MODEL`, optional `AGENT_API_KEY`) live only in the JS env; **none is added to `config/settings.py`**, and `ANTHROPIC_API_KEY` is **removed** from settings.py + `.env.example` (reconciliation #3). Server-only vars (`AGENT_*`) carry no `NEXT_PUBLIC_` prefix and never appear in the browser bundle — including via prop-drilling or RSC serialization.
- **Violated when**: an `AGENT_*` literal value appears in the built client bundle; a `NEXT_PUBLIC_AGENT*` var exists; an `AGENT_*` var is wired into `config/settings.py`; or the "agent unavailable" copy echoes `AGENT_BASE_URL`.
- **Enforcement**: after `next build`, scan `web/.next/static/**/*.js` for the **literal sentinel values** of `AGENT_*` set at build time → assert none present; assert no `NEXT_PUBLIC_AGENT*`; source grep as backstop. Python side: a `settings.validate()`-with-UI-vars-unset test asserts `AGENT_*` are absent from the required set and `ANTHROPIC_API_KEY` is gone (user-gated test regeneration).
- **Test approach**: integration

### INV-010: The Node tree does not break the Python toolchain (decomposed) [integration]
- **Type**: must · **Category**: data-integrity · **Boundary**: composes with PAT-013
- **Statement**: Adding `web/` leaves the Python toolchain green, via individually-failing assertions: (1) `git check-ignore web/node_modules/ web/.next/ web/.env.local` all succeed even when those paths do not exist (entries added to `.gitignore`; directory arguments include trailing slashes); (2) the built wheel contains no `web/` path, and `pyproject.toml` `[tool.hatch.build.targets.wheel].packages` stays a **hardcoded list** that never includes `web` (never switch to glob/auto-detect — AP-024); (3) a uniquely named temporary Python file under `web/` with deliberate ruff violations is **not** flagged even when explicitly passed to Ruff (`extend-exclude` includes `web` and `force-exclude` is enabled; Ruff never walks `web/node_modules`); (4) detect-secrets excludes `web/` lockfiles/bundles (or `.secrets.baseline` is regenerated) so commits aren't blocked; (5) `uv run --frozen python -m pytest` + `uv run --frozen python -m ruff check .` pass with `web/` present. Each Ruff assertion independently provisions its own temporary violating file, works on a checkout with no frontend files, and cleans up only its own artifacts. Tests must not overwrite an existing web file or depend on test order.
- **Violated when**: any of (1)–(5) fails, or `web/` artifacts get committed / re-enter Python lint scope.
- **Enforcement**: the five named CI assertions above + `.gitignore`/`pyproject.toml`/`.pre-commit-config` edits reviewed.
- **Test approach**: integration

### INV-011: No PII collected, stored, logged, or transmitted client-side; transcripts ephemeral
- **Type**: must-not · **Category**: security · **Boundary**: TB-004, composes with operator-ui INV-005
- **Statement**: The client collects only pseudonymous `participant_id` (UUID-validated before submission); never collects, persists, logs, or transmits PII. The agent route is `dynamic`/`no-store` (no Next.js Data Cache / RSC caching of session-derived responses); the chat/session store is React state/context only — no `localStorage`/`cookie`/`IndexedDB`/framework persistence of session-derived content. Any actionable result (e.g. a created `session_id`) is also surfaced in the durable session list, not only the ephemeral chat.
- **Violated when**: a non-UUID `participant_id` submits; a PII form field exists; session/chat content persists to any durable store; or the agent route is cacheable.
- **Enforcement**: CI test — form rejects non-UUID; no PII fields; spies on `Storage.prototype.setItem`, the cookie setter, and `indexedDB` assert nothing session-derived persists after a session-derived chat message; assert the agent route sets `no-store`/`dynamic`. Grep backstop.
- **Test approach**: integration

### INV-012: Every state-change claim is backed by a rendered API-sourced tool-result [integration]
- **Type**: must · **Category**: security (anti-fabrication) · **Boundary**: TB-006, guards PRH-004
- **Statement**: Any assistant claim of a state-changing action (created/closed/started/ran) renders only as a tool-result card sourced from an actual API response; assistant **prose alone never renders as a completed action**. A narrated tool intent with no corresponding completed/failed tool result renders a visible "action did not complete" state. Streamed prose contradicting a tool's `409`/error does not render as success.
- **Violated when**: a completed-action affordance renders from prose without a backing API response, or a 409 tool-result coexists with an un-corrected "done" rendering.
- **Enforcement**: CI test — stub the model to emit prose claiming a close with no tool call → assert no success card renders; stub a `close_session` 409 → assert the rendered state is the refusal, not success.
- **Test approach**: integration

### INV-013: The agent route validates AGENT_BASE_URL is loopback/private before any outbound call
- **Type**: must · **Category**: security (SSRF) · **Boundary**: TB-006
- **Statement**: Before any outbound request, the route validates `AGENT_BASE_URL`'s host is loopback (`127.0.0.0/8`, `::1`, `localhost`) or RFC-1918 private range (or an explicit allow-list) and the scheme is `http`/`https`; otherwise it refuses to call and fails closed (INV-007 path). Session-derived text is never POSTed to a public/non-allow-listed host.
- **Violated when**: the route issues an outbound call to a non-loopback/non-private host, or skips validation.
- **Enforcement**: CI unit test feeding `AGENT_BASE_URL` values (`169.254.169.254`, a public host, a `file://` scheme) → assert no outbound call and a fail-closed result; a loopback value → allowed.
- **Test approach**: unit

### INV-014: The agent route caps tool-calls per turn / loop iterations
- **Type**: must · **Category**: security (DoS) · **Boundary**: TB-006
- **Statement**: A single chat turn cannot drive unbounded tool calls; the route enforces a fixed max tool-calls-per-turn / agent-loop iteration bound and fails closed (stops, surfaces a "step limit reached" message) when exceeded — bounding agent-amplified read storms against the read-only DB role.
- **Violated when**: the agent loop has no iteration cap, or an injected "poll repeatedly" instruction yields unbounded API round-trips.
- **Enforcement**: CI test — stub the model to emit a tool call every step; assert the route halts at the configured cap and surfaces the limit message.
- **Test approach**: unit

### INV-015: Malformed/absent model tool emission is handled without crashing the stream [integration]
- **Type**: must · **Category**: functional · **Boundary**: TB-006, BND-002
- **Statement**: When the model endpoint is reachable but emits malformed tool-call JSON, a tool name not in the registry, wrong-typed args, or no tool call at all, the route rejects/handles it without crashing the stream and surfaces a clear "could not complete" state (distinct from `agent_unavailable`).
- **Violated when**: a malformed/absent emission throws unhandled, crashes the stream, or forwards invalid args to FastAPI.
- **Enforcement**: integration test feeding each malformed-emission shape from a fake model → assert a structured handled outcome, no crash, no forwarded call.
- **Test approach**: integration

### INV-016: Every tool call and API request has a defined in-flight state [integration]
- **Type**: must · **Category**: functional (UX) · **Boundary**: TB-004
- **Statement**: Each tool call and API request exposes a defined in-flight indicator; the chat surfaces tool-call status (issued / awaiting / returned) distinctly from model prose, so the operator can always distinguish working from hung from completed.
- **Violated when**: a request in flight renders no pending state, or tool-call progress is indistinguishable from prose.
- **Enforcement**: CI test with a deferred (pending) transport → assert a loading/in-flight affordance renders before resolution and clears after.
- **Test approach**: integration

### INV-017: The frontend test gate is wired and required-green [integration]
- **Type**: must · **Category**: process · **Boundary**: composes with PAT-008 (Python gate analog)
- **Statement**: A JS lane (`pnpm install && next build && pnpm test && pnpm lint`) is registered in `.correctless/config/workflow-config.json` (a non-empty `build`/JS test command or monorepo package entry) and in CI, required-green before merge. The frontend invariants' "CI test assertion" enforcement is real, not aspirational. (Resolves OQ-005; the Correctless `source_file` gate remains `*.py`, so the JS lane is the frontend gate of record.)
- **Violated when**: `web/` invariants can ship with a green Correctless run and zero JS assertions executed.
- **Enforcement**: a meta-test asserts the CI config contains the JS lane and that `pnpm test`/`pnpm lint` run on `web/`.
- **Test approach**: integration

### INV-018: contract_version skew is surfaced, not silently tolerated
- **Type**: must · **Category**: functional · **Boundary**: TB-004, BND-001
- **Statement**: The client reads `contract_version` from `GET /health` and surfaces a "backend/frontend version mismatch" banner when it diverges from the version the shell was built against, rather than degrading silently. `gate` and other server strings are treated as opaque display text (a gate-numbering drift does not blank INV-006 messages).
- **Violated when**: a `contract_version` mismatch renders capabilities wrong with no warning.
- **Enforcement**: CI test mocking a mismatched `contract_version` → assert the banner renders.
- **Test approach**: integration

### INV-019: Newly-enabled write/exec capabilities require first-use confirmation
- **Type**: must · **Category**: safety · **Boundary**: TB-004, composes with PAT-011
- **Statement**: When a capability transitions `blocked`/`scaffolded` → `implemented` (observed via `/capabilities` after a backend upgrade), the first invocation of a write/exec capability (capture start/stop, close session, `arc:run`, marker publish) requires an explicit operator confirmation affordance — not a silently flipped flag a researcher could trigger by reflex.
- **Violated when**: a newly-live write/exec capability executes on first use with no confirmation.
- **Enforcement**: CI test flipping a capability to `implemented` → assert the first write/exec invocation prompts confirmation before issuing the request.
- **Test approach**: integration

## Prohibitions

### PRH-001: Client/route never sends tenant scope
- **Statement**: No `web/` request (browser client or agent route) carries `sponsor_id`/`site_id`. · **Detection**: contract test + grep (INV-004). · **Consequence**: normalizes client-controlled tenancy, undermining server-injection when auth lands.

### PRH-002: Model cannot supply URL / path / SQL / shell
- **Statement**: No tool/route lets the model supply a raw endpoint URL, filesystem path, SQL, or shell; tools map to fixed endpoints with typed args only. · **Detection**: tool-schema unit tests + name→path map test (INV-003). · **Consequence**: SSRF / injection / path traversal via the agent.

### PRH-003: No HTML injection / eval of session-derived text
- **Statement**: Session-derived strings (incl. echoed 422/409 content) are never rendered via `dangerouslySetInnerHTML` or `eval`/`Function`. · **Detection**: lint/grep ban + injection render test (INV-005a). · **Consequence**: stored-XSS.

### PRH-004: No fabricated success for any action
- **Statement**: The shell never renders a completed-action affordance not backed by an API tool-result; never synthesizes success for a `blocked`/`scaffolded` capability. · **Detection**: INV-012 / INV-002a / INV-008a (client/route half); INV-002b/INV-008b model half is eval/review-only — **explicitly not closed by the unit gate**. · **Consequence**: operators believe an action happened (capture started, session closed) when nothing did — safety/data-integrity hazard.

### PRH-005: Server-only agent secrets never reach the browser
- **Statement**: `AGENT_*` are server-route-only; no `NEXT_PUBLIC_` exposure; no leak via prop/RSC. · **Detection**: built-bundle sentinel scan (INV-009). · **Consequence**: local-model endpoint/key leaked to the browser.

### PRH-006: Node build artifacts never committed or gating-breaking
- **Statement**: `web/node_modules`, `web/.next`, `web/.env.local` are gitignored; `web/` never breaks `uv run pytest`/`ruff` or re-enters Python lint scope. · **Detection**: `git check-ignore` + wheel-content + pre-commit-trap (INV-010). · **Consequence**: repo bloat; broken Python gate.

### PRH-007: AGENT_BASE_URL is never called when non-loopback/non-private
- **Statement**: The route never issues an outbound call to a public/non-allow-listed host. · **Detection**: INV-013 test. · **Consequence**: SSRF egress + session-text exfiltration.

## Boundary Conditions

### BND-001: API responses into the client
- **Boundary**: TB-004 (response) · **Input from**: FastAPI responses · **Validation**: handle every status (200/409/422/503/404), null `blocked_reason`/`gate`, empty list, and `contract_version`; unknown shape → fail-closed message. · **Failure mode**: fail-closed.

### BND-002: Local-model tool-call arguments and emissions
- **Boundary**: TB-006 (LLM-generated) · **Input from**: the model's emitted tool calls (untrusted) · **Validation**: validate every arg against the closed schema before forwarding; handle malformed/absent emissions (INV-015); FastAPI re-validates independently. · **Failure mode**: fail-closed (reject; do not forward; do not crash the stream).

### BND-003: Session-derived text into the DOM and model context
- **Boundary**: TB-004 (DOM) + TB-006 (context) · **Input from**: session data / API responses · **Validation**: DOM-escape (INV-005a); fence as data in model context (INV-005b). · **Failure mode**: fail-closed (inert by default).

### BND-004: Operator chat input → agent route
- **Boundary**: TB-006 · **Input from**: free-text operator chat (untrusted instruction surface) · **Validation**: the route pins the tool set + system prompt (operator text cannot redefine tools or inject system instructions); caps loop iterations (INV-014); tools gate on capability status. · **Failure mode**: fail-closed (out-of-registry intents refused; model-refusal half is eval/review-only).

### BND-005: AGENT_BASE_URL egress target
- **Boundary**: TB-006 · **Input from**: operator env config · **Validation**: loopback/private-range + scheme check before any call (INV-013). · **Failure mode**: fail-closed (refuse the call).

## STRIDE Analysis

### STRIDE for TB-004: Browser client → API
- **Spoofing**: No auth in M0 (localhost, single operator — EA-001, accepted). Tenancy server-injected (INV-004). **Accepted M0 risk (RS-011):** an unauthenticated localhost API with no CORS/Origin/Host policy is reachable by a malicious browser tab (CSRF) or DNS-rebinding; documented in decisions.md alongside operator-ui BND-004; a CORS/Origin/Host allow-list is a follow-on item when auth lands (OQ-001).
- **Tampering**: client cannot weaken server validation — FastAPI re-validates (INV-002a/008a).
- **Repudiation**: out of scope M0 (no per-user identity).
- **Information disclosure**: no PII (INV-011); error copy mapped, not raw (INV-006).
- **DoS**: `POST /sessions` spam accepted (operator-ui BND-004); agent-amplified read storms capped (INV-014).
- **EoP**: closed typed registry, no tenancy/URL/SQL/shell/path (INV-003, PRH-002).

### STRIDE for TB-006: Agent route → local model (NEW — author in ARCHITECTURE.md)
- **Spoofing/Tampering**: `AGENT_BASE_URL` egress restricted to loopback/private (INV-013); model output (tool-call JSON, prose) is untrusted input re-entering the Node route — validated (BND-002, INV-015) and never rendered as completed action without an API tool-result (INV-012).
- **Repudiation**: n/a M0.
- **Information disclosure**: session-derived text fenced as data (INV-005b) and never POSTed off-host (INV-013); `AGENT_*` secrets server-only (INV-009/PRH-005).
- **DoS**: bounded timeout (INV-007) + loop cap (INV-014); stalled model fails closed.
- **EoP**: prompt-injection via session text cannot escalate — closed registry + server re-validation; the worst case (a schema-valid in-registry `create_session`) is a junk session in M0, mitigated by INV-012/INV-019.

### STRIDE for TB-005: LSL → WS → browser (placeholder in M0)
- The live-signal tab renders a placeholder, does not open the WebSocket (server refuses the upgrade), and shows the scaffolded reason. Full STRIDE deferred to the live-tap milestone (operator-ui INV-008b). M0 invariant: the tab — and any model-invoked client-nav tool like `view_live_signals` — must not initiate a WS upgrade or create tap resources.

## Environment Assumptions
- **EA-001**: M0 is localhost-bound, single operator, no auth — composes with operator-ui EA-001/EA-003. No auth/login affordances implying isolation that doesn't exist.
- **EA-002**: FastAPI is running at `API_BASE_URL` with tenancy configured; otherwise reads `503` → mapped message (INV-006). `API_SPONSOR_ID`/`API_SITE_ID` examples added to `.env.example`.
- **EA-003**: A local OpenAI-compatible endpoint (LiteLLM proxy) is reachable at `AGENT_BASE_URL`; absence/unreachability/stall degrades only the agent route (INV-007). LiteLLM config is outside the repo.
- **EA-004**: Frontend env vars live in the JS env; `ANTHROPIC_API_KEY` is removed (reconciliation #3). `web/.env.example` ships with a default `AGENT_BASE_URL` (e.g. `http://localhost:4000` for LiteLLM) + `AGENT_MODEL`.
- **EA-005**: Node.js toolchain present; **Node major/LTS pinned** in `web/package.json` `engines`. Python/`uv` toolchain independent (INV-010).
- **EA-006**: Package manager is **pnpm** (aligns with operator-ui EA-007); OQ-003 resolved on this point.
- **EA-007**: Dev/CI OS includes Windows (repo is Windows); `web/` globs, line endings, and `next build`/pnpm must work on Windows.
- **EA-008**: A dedicated `web/` dev/prod port is reserved (distinct from API `:8000`, DB `:5435`, LiteLLM `:4000`).
- **EA-009**: The agent route's egress posture is **loopback/private only** (INV-013); this resolves the contradiction with operator-ui EA-008 ("outbound HTTPS to the model provider") — operator-ui EA-008 is updated to the LiteLLM-local-proxy posture (reconciliation #3).
- **EA-010**: A bounded agent-route timeout is configured (INV-007).

## Open Questions
- **OQ-001**: Pin the **AI SDK major version** before INV-003 is implemented; state registry/arg-schema invariants in version-agnostic terms with a confirm-at-install note. (Was deferred; now a pin requirement.)
- **OQ-002**: Styling / component approach (Tailwind, shadcn/ui, or plain CSS) — out of the contract; decide at implementation.
- **OQ-003**: `web/` layout (sibling dir vs workspace) — package manager resolved to pnpm (EA-006); layout still open, affects only tooling.
- **OQ-004**: Confirmed: M0 chat transcripts are ephemeral/in-memory (INV-011); no durable store introduced.
- **Backlog (follow-on, recorded against api/operator-ui):** (a) server-side length/charset bounds on `create_session` free-text fields (RS-010); (b) CORS/Origin/Host allow-list on the FastAPI surface when auth lands (RS-011).
