# Verification: Operator UI — Staged Agentic Surface (M0)

- Spec: `.correctless/specs/operator-ui.md` (Intensity: high; effective intensity: high)
- Branch: `feature/phase-4-ui` (feature work is uncommitted working-tree state; HEAD `0dcad4d` predates it)
- Date: 2026-06-12
- Verifier: /cverify (did not participate in implementation)

## Test Evidence (run fresh during verification)

- `uv run pytest tests/api_tests -q` → **70 passed**, 1 warning, 2.95s
- `uv run pytest -q` (full suite) → **10 failed, 367 passed, 4 skipped** — the 10 failures
  are exactly the pre-existing capture-layer failures enumerated in the tdd-impl override
  and the decisions-log "Backend Debt Deferred" entry (ECHO ingestion integration x5, ARC
  baseline persistence x4, session_close r021 x1). None touch `api/` or `tests/api_tests/`.

## Rule Coverage

| Rule | Test | Status | Notes |
|------|------|--------|-------|
| INV-001 | test_tenancy.py (4 tests), test_tenancy_not_configured.py, test_validation_fail_closed.py | covered | integration; cross-sponsor filtering, body-tenancy rejection, never-None-sponsor spy, None-tenancy 503 fail-closed with no-DB tripwire |
| INV-002 | test_readonly_role.py | covered | integration; load-bearing tests use the REAL `api.deps.get_readonly_connection()` factory (SELECT ok, INSERT/UPDATE raise InsufficientPrivilege); generic closed-SQL scan over ALL api.* submodules incl. api.arc |
| INV-003 | test_no_pii.py::test_api_modules_never_insert_echo_events | covered | unit backstop scan + read-only role (structural); capability blocked in M0 |
| INV-004 [integration] | test_validation_fail_closed.py | covered | malformed UUID 422 no-DB, SQLi path-id rejected no-DB, unknown-key 422, body tenancy rejected |
| INV-005 | test_no_pii.py | covered | response models discovered from actual route table, subset of pinned allowlist, extra='forbid' asserted, PII field check; participant_id UUID 422; logger blocklist backstop lives in tests/capture_tests/logger/test_logger.py (pre-existing PAT-001 coverage) |
| INV-006 [integration] | test_arc_watermark_gate.py | covered | B1 fix: gate extracted as `api.arc.assert_session_arc_ready` and exercised against real DB; watermark states genuinely DERIVED via the 024 trigger (seed drives real status transitions and the test verifies the trigger fired); positive verified case present |
| INV-007 [integration] | test_create_session.py | covered | real `create_session` validation (not mocked) through TestClient; structured 422 {field, message, valid_choices}; valid_choices == VALID_COMPOUNDS/VALID_DOSE_UNITS; /vocab sourced from canonical sets |
| INV-008a | test_ws_tap_isolation.py, test_capability_gating.py::test_scaffolded_ws_refuses_upgrade... | covered | upgrade refused with app-defined close code 4409 + structured JSON capability reason (not default 1000); no StreamThread/forwarder import |
| INV-008b | — | deferred by spec | re-typed `must` at the tap milestone; not M0 scope |
| INV-009 | test_capability_gating.py::test_capture_start_does_not_construct_forwarder_engine (+ 409 param cases) | covered (weak labeling) | M0 enforcement (409 + no process spawned) is fully tested, but no test cites INV-009 by ID — grep for "INV-009" finds nothing. Post-OQ-004 platform-signal assertions deferred by spec. |
| INV-010 [unit] | test_frames.py | covered | lsl_timestamp axis, db_insert_time can never leak, multi-row order |
| INV-011 | test_config_access.py | covered | source scan: no os.environ/os.getenv/load_dotenv in api/ |
| INV-012a | test_endpoint_set.py | covered | exact route-set equality (missing AND extra fail), unknown path 404, WS route present, behavioral half (B4): client-supplied tenant scope 422 |
| INV-012b | — | code-review (by design) | spec types this code-review-enforced in M0; no JS registry code exists yet (see Drift D-2); future Vitest harness named in spec |
| INV-013 | test_capability_gating.py, test_capabilities_discovery.py | covered | 409-first (even before UUID validation), structured body, no-DB tripwire patches driver AND api factories, backend-not-called spies (run_arc_post_session, ForwarderEngine, session_close.workflow.run), /capabilities full-matrix discovery |
| INV-014 | test_db_down.py, test_create_session.py, test_capability_gating.py | covered (API mapping half) | 503 backend_unavailable on all 3 DB-touching endpoints; structured 422/404/409 bodies carry actionable messages. Client rendering half is JS-harness/code-review per spec — no client exists (Drift D-2). |
| INV-015 | test_settings_optional.py, test_tenancy_not_configured.py::test_settings_validate_unaffected... | covered | UI vars optional via _get_optional; validate() unaffected. Minor: test_validate_succeeds_with_ui_vars_unset can pytest.skip on unrelated env failure — acceptable, the named-var assertion still ran. |
| PRH-001 | test_no_pii.py, test_readonly_role.py | covered | no write to audit_events possible (role + scan); api.arc's read-only SELECT on audit_events explicitly permitted and scanned |
| PRH-002 | test_no_pii.py, test_readonly_role.py | covered | echo_events write impossible (role + scan) |
| PRH-003 | test_readonly_role.py::test_read_sql_constants_are_read_only, test_validation_fail_closed.py::test_sql_injection_path_id_rejected_no_db | covered | all SQL constants `%(name)s`-bound (verified by read of api/sessions.py, api/arc.py); SQLi string rejected at validation |
| PRH-004 | test_arc_watermark_gate.py | covered | arc:run on failed session 409; gate raises for all non-verified states |
| PRH-005 | test_no_pii.py + capture logger test | covered | bounded by INV-005 allowlist + PAT-001 blocklist backstop |
| PRH-006 | test_endpoint_set.py (server side) | covered (server half) | no endpoint accepts SQL/shell/path/tenancy; agent-side registry does not exist yet (Drift D-2) |
| PRH-007 | test_capability_gating.py | covered | 409 + no-DB + backend-not-called, raw HTTP client per spec |
| BND-001 | test_validation_fail_closed.py | covered | |
| BND-002 | — | deferred by spec | WS tap milestone (with INV-008b / OQ-003) |
| BND-003 | server-side via INV-004/INV-012a tests | covered (server half) | model-side tool schema has no code yet (Drift D-2) |
| BND-004 | test_db_down.py + docs/decisions.md "Operator UI M0 — Accepted DoS Risk" | covered via accepted-risk branch | BND-004's documented-acceptance branch taken (QA-003): caps not implemented, exhaustion → OperationalError → structured 503, decision recorded |

**Uncovered rules: none.** Every spec rule with a pytest-enforceable M0 contract has a
passing test; rules typed code-review/deferred by the spec are accounted for above.

## Dependencies

Diffed `pyproject.toml` against HEAD (no local `main`; remote default is `origin/main`):

- + `fastapi>=0.136.3` — API framework (api/app.py). Named in spec Upgrade/Install. License: MIT. Actively maintained.
- + `uvicorn>=0.49.0` — ASGI server (runtime entry; not imported by tests). Named in spec. License: BSD-3-Clause. Actively maintained.
- + `websockets>=16.0` — WS support. Named in spec. License: BSD-3-Clause. Note: not directly imported by api/ in M0 (starlette handles the WS route); declared ahead of the tap milestone.
- + `httpx>=0.28.1` (dev) — required by fastapi/starlette TestClient. Consistent with spec's CI requirements (not individually named — minor, dev-only).
- `uv.lock` regenerated; `[tool.hatch.build.targets.wheel].packages` gained `api` per spec Upgrade/Install.
- No known-CVE flags on these pins at verification time (fastapi/uvicorn/websockets current major lines); no abandoned packages.

## Compliance Checks

`workflow.compliance_checks` is not configured — skipped (dormant).

## Architecture Adherence

Entries added by this spec (RS-005/RS-006, authored before code) and affected entries checked
against the implementation:

- PAT-010: valid — api/ wraps `session_init.workflow.create_session` (module-attribute access), read SQL constants all `^(SELECT|WITH)` with no write token, read-only role enforced structurally and by integration tests; no SessionRepository/ORM introduced.
- PAT-011: valid — capability matrix single-sourced in `api/capabilities.py`, 409-first behavior implemented and tested, WS refuses upgrade with capability reason, `GET /capabilities` discovery live.
- TB-004: valid — server-side invariants implemented and tested; agent/browser side not yet built (consistent with the entry's forward-looking text; see Drift D-2).
- TB-005: valid — forward-looking; M0 honors it (frames.py uses lsl_timestamp; ws.py imports no forwarder internals; tap not live).
- TB-001 (affected by config/settings.py change): valid — new UI vars use `_get_optional`, validate() unaffected (tested).
- TB-003 (affected by tenancy-scoped reads): valid — all api/ reads filter by server sponsor_id; never called with None (tested).

These entries use the house prose format (no machine `Enforced at:`/`Test:` file-path fields),
so path-existence/test-ID checks are N/A for them; invariant-conflict checks all pass.

0 stale entries. **Caveat:** the deterministic antipattern scanner and any diff-based
architecture check ran against a HEAD fallback diff (`main` is not a local branch and the
feature is uncommitted), so the untracked `api/` + `tests/api_tests/` trees were verified by
direct read, not by diff tooling.

### Drift Debt
`.correctless/meta/drift-debt.json` is absent — drift-debt surfacing dormant (PAT-019).
No entries written yet; see Drift section (human disposition required).

## QA Class Fixes Verified

- QA-001 (BLOCKING, fixed): app-level `psycopg2.OperationalError` handler returning structured 503 in `api/app.py` — present; class-level test `tests/api_tests/test_db_down.py` covers all 3 DB-touching endpoints by patching the connection factory / driver. VERIFIED.
- QA-002 (BLOCKING, fixed): closed-SQL scan generalized to iterate ALL `api.*` submodules via `pkgutil` in BOTH test_readonly_role.py and test_no_pii.py, with explicit assertions that `api.arc` / `WATERMARK_EVENTS_FOR_ARC_SQL` are discovered. Class of bug (future module escaping the scan) covered, not just the instance. VERIFIED.
- QA-003 (fixed): BND-004 accepted-risk decision recorded in `docs/decisions.md` ("Operator UI M0 — Accepted DoS Risk"), exhaustion path inherits the QA-001 503 handler. VERIFIED.
- QA-004 (fixed): typed `ConfigurationError` + `require_tenant` mapped to 503 `tenancy_not_configured`; None path pinned by test_tenancy_not_configured.py with no-DB tripwires. Implementation splits resolve (no raise) from enforce (raise) so INV-004's 422-before-tenancy ordering holds — a documented, acceptable variant of the class fix. VERIFIED.
- QA-005 (fixed): `api/app.py` imports the `deps` module and calls `deps.get_readonly_connection()` at call time; test_db_down patches `api.deps.get_readonly_connection` and the patch binds. VERIFIED.
- QA-006 (fixed): `config/settings.py` comment now states the API read path REQUIRES `API_READONLY_DATABASE_URL` and fails loud with NO TEST_DATABASE_URL fallback. VERIFIED.

## Antipattern Scan

`bash .correctless/scripts/antipattern-scan.sh main` → valid JSON, `{"findings": []}`, no
errors array. **Scanner limitation:** stderr warned `git diff main...HEAD failed, falling
back to HEAD diff`; because the feature code is untracked, the diff-based scanner did not
actually scan `api/` or `tests/api_tests/`. A manual review of all 9 api/ modules and 18
test files was performed instead (semantic ai-antipatterns checklist file
`.correctless/checklists/ai-antipatterns.md` does not exist in this install — skipped).

## Smells

- `api/ws.py` vs `api/app.py` duplication (LOW): `WS_CAPABILITY_CLOSE_CODE = 4409` is defined in api/ws.py and re-defined as `_WS_CAPABILITY_CLOSE_CODE = 4409` in api/app.py; the WS route in app.py builds its close reason inline instead of calling `ws.capability_close_reason()`. `api.ws` is imported by no production module — it exists chiefly to satisfy test_ws_tap_isolation's tap-module file scan. Suggest app.py consume `api.ws`'s constant/helper when the tap milestone lands.
- No TODO/FIXME/HACK/debug statements, no commented-out code, no broad `except Exception` in api/ (the two `except` blocks catch `ValueError` and `(ValueError, TypeError, AttributeError)` — specific).
- `tests/api_tests/test_arc_watermark_gate.py:58-60`: `assert_session_arc_ready(...) is None or True` is a vacuous expression (always truthy, asserts nothing) — the real check is that the call does not raise, which it does exercise, so coverage is intact; the expression is just dead. Cosmetic.

## Drift (human disposition required)

- **D-1 — INV-016 is not a spec rule ID.** `tests/api_tests/test_watermark_state.py`, `support.py`, and `api/sessions.py` cite `INV-016`; the spec defines the watermark_state enum in the Endpoint contract under **RS-016**, and its invariants stop at INV-015. The behavior itself is spec-pinned and tested; only the rule-ID label is phantom. Options: fix labels to RS-016 (recommended, doc-only), or upgrade the spec to add INV-016 (user-gated spec change).
- **D-2 — M0 frontend shell absent.** The spec's M0 Capability Status matrix says "Agent tool execution — scaffolded (registry visible, execution disabled)" and scaffolded "tab placeholder"s, EA-007 declares the Node/pnpm/Next.js toolchain, and the Upgrade/Install section requires `web/` gitignore entries, `web/.env.example`, and a CI JS lane. The decisions-log entry likewise says M0 ships "empty live/ARC tabs + a status-flagged tool registry with execution disabled." **No `web/` tree exists.** Every load-bearing (server-side) control is implemented and tested; the UX shell is not. Options: (1) narrow the spec's M0 matrix to the API surface and move the shell to an M0.5/M1 milestone (recommended — matches what was actually built and reviewed), (2) log as DRIFT debt, (3) build the shell before merge.
- **D-3 — decisions-log wording predates the spec.** The first "Operator UI — Staged Agentic Surface" decision says blocked capabilities are "endpoints absent or `501`"; the spec (and implementation) settled on present-and-`409` capability-status. The spec is the contract authority and the implementation follows it; the decision entry's wording is stale. Fix in /cdocs (doc-only).
- **D-4 — INV-009 ID untraceable in tests.** Coverage exists (see matrix) but no test cites INV-009. Add the rule ID to the capture-start/stop test docstrings at next test regeneration (user-gated; do not hand-edit tests outside the spec→test flow).

## Spec Updates

- 1 post-approval spec update during TDD: +44 lines (421 → 465), the QA-001..QA-006 contract upgrades (503 backend_unavailable mapping, tenancy-not-configured 503, BND-004 acceptance, closed-SQL scan generalization). /creview-spec re-run was skipped via a logged override with rationale recorded in docs/decisions.md ("Backend Debt Deferred" item 2).

## Process Findings (advisory)

- **P-1 (HIGH advisory): full-suite gate is red and temporarily bypassed.** `workflow-config.json` `commands.test` is scoped to `tests/api_tests` with a TEMP note reading "the 10 failures must be resolved before /cverify+merge", while the later, authoritative decisions-log entry defers them as backend debt and restores the full-suite gate at docs time. The two records conflict on timing. Decisions log wins per repo rules, but: the `commands.test` value MUST be restored to `uv run pytest` during /cdocs, and the 10 capture failures remain a visible red gate until fixed. Do not treat this feature's merge as evidence the capture debt is paid.
- **P-2: workflow phase was already `done`** when /cverify ran (the pipeline advanced past verify without this report existing). This report repairs the missing artifact; the `workflow-advance.sh verified` transition is a no-op/invalid from `done` and any failure of that call is expected.

## Overall: PASS — 0 uncovered rules, 0 blocking findings; 4 drift items pending human disposition; 2 process advisories; 3 low-severity smells

api_tests evidence: 70/70 passed. QA class fixes: 6/6 verified. New deps: 3 runtime + 1 dev, all spec-sanctioned.
