# Dev Journal

## 2026-06-12 — Operator UI — Staged Agentic Surface (M0)

This feature gives blackRabbit its first user surface: a thin FastAPI layer
(`api/`) that an eventual Next.js chat GUI (Vercel AI SDK agent with pinned
tools) will sit on. The core design problem was that the backend's riskiest
areas — capture process ownership, ARC-before-`watermark_verified`, real
authentication — are unsettled, so exposing them through an agent would
multiply risk. The answer is staging by capability status: every capability in
the spec's matrix is `implemented`, `scaffolded`, or `blocked`, and the gate is
server-side. A blocked endpoint is *present* and returns a structured
`409 Capability unavailable` body unconditionally and first — before any
validation or DB connection — so nothing can happen en route to refusal
(PAT-011). The scaffolded WebSocket refuses the upgrade with a capability
close reason. `GET /capabilities` exposes the whole matrix so a client can
source tool state at runtime instead of hardcoding it.

The code is nine modules: `app.py` (the `create_app()` factory, route wiring,
and app-level exception handlers), `deps.py` (tenant context from
`settings.API_SPONSOR_ID`/`API_SITE_ID`, the read-only connection factory, and
a typed `ConfigurationError`), `sessions.py` (read queries + the
`create_session` wrapper), `arc.py` (watermark-state derivation),
`capabilities.py` (the status registry), `vocab.py`, `frames.py`, and `ws.py`.
M0 implements health, capabilities, vocab, session list/status, and session
create; create wraps `capture.session_init.workflow` rather than duplicating
it (PAT-010). Direct SQL is read-only in a structural sense: the API connects
through `API_READONLY_DATABASE_URL`, a `GRANT SELECT`-only Postgres role, so a
write raises `InsufficientPrivilege` at the driver no matter what SQL slips
through. SQL lives in module-level `*_SQL` constants (PAT-003) and a
generic scan asserts every `api.*` constant matches `^(SELECT|WITH)`.

Trust-boundary mechanics (TB-004): the client and the model are both
untrusted, identically. Tenancy is never accepted from a request — it is
server-injected from settings, and a missing tenancy config maps to a typed
503 ("API tenancy not configured") rather than a silent fallback. All input is
validated fail-closed before any DB call; responses serialize through a closed
field allowlist (no PII, UUID `participant_id` only). DB-down maps to
`503 {"error":"backend_unavailable"}` via an app-level
`psycopg2.OperationalError` handler so every DB-touching route inherits it —
that handler is also the accepted-risk answer to connection exhaustion in M0
(localhost-bound, see decisions.md "Operator UI M0 — Accepted DoS Risk").

Two QA-driven conventions worth knowing before touching this code. First,
patchable factories are called via module attribute (`deps.get_readonly_connection()`),
never name-bound at import — import-time binding creates a shadow that test
patches on `api.deps` never reach (PAT-012; this was QA-005). Second, the
read-only/no-write scan iterates *all* `api.*` submodules generically, so a
new module that defines SQL cannot escape the assertion (QA-002). The
api_tests suite (70 tests, `tests/api_tests/`) runs DB-free by default through
no-DB tripwire fixtures in `conftest.py`; integration tests use the real
read-only role and the 024 watermark trigger. The 10 pre-existing
capture-layer failures and the Next.js shell are deferred — see
`docs/2R/backlog.md` "Operator UI — Deferred / Skipped Register".
