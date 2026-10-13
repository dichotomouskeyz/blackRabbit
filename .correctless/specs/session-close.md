# Spec: Session Close

## Metadata
- **Task**: session-close
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/session_close` runs end-of-session reconciliation and closes the session. It: reads XDF sample counts, connects to the DB, validates the session is in a closeable state, transitions it to `closing` if still `active`, compares XDF vs DB counts (backfilling any positive gaps from XDF data), runs ARC post-session processing, then calls `close_session` which sets status to `closed` or `failed` and fires the watermark trigger. Returns an integer exit code: `0` (closed and reconciled), `1` (failed — gaps remain or ARC failed), `2` (pre-condition error — XDF unreadable, session not found, or wrong state).

`run()` accepts `xdf_path` as any path-like value (`str` or `pathlib.Path`) and coerces it to `Path` at entry — callers beyond the CLI (future UI/API) hand over string paths.

## Rules

### State machine — unit tests

- **R-001** [unit]: `validate_entry_state` returns the status string when the session exists and status is `'active'` or `'closing'`.

- **R-002** [unit]: `validate_entry_state` returns `None` for any status outside `VALID_ENTRY_STATES` (e.g. `'closed'`, `'failed'`, `'initializing'`).

- **R-003** [unit]: `ensure_closing` calls `set_closing` and logs a warning when status is `'active'`.

- **R-004** [unit]: `ensure_closing` is a no-op (no DB call, no log) when status is already `'closing'`.

- **R-005** [unit]: `exit_code_for_report` returns `0` when `report.is_reconciled` is `True`.

- **R-006** [unit]: `exit_code_for_report` returns `1` when `report.is_reconciled` is `False`, and logs stream gaps at ERROR level.

### XDF read — unit tests

- **R-007** [unit]: `read_xdf_counts_or_none` returns `None` and logs at ERROR when the XDF file raises `XDFTruncatedError`.

- **R-008** [unit]: `read_xdf_counts_or_none` returns `None` and logs at ERROR when the XDF file raises `XDFReadError`.

### Exit codes — integration tests

- **R-009** [integration]: `run()` returns `2` when the XDF file is unreadable (before DB connection is opened).

- **R-010** [integration]: `run()` returns `2` when the session does not exist in `sessions` for the given `session_id` and `sponsor_id`.

- **R-011** [integration]: `run()` returns `2` when the session exists but is in a non-closeable state (`'closed'`, `'failed'`, `'initializing'`).

- **R-012** [integration]: `run()` logs a WARNING and transitions the session to `'closing'` when it is still `'active'` at call time, then continues.

### Reconciliation — integration tests

- **R-013** [integration]: When all stream counts match (XDF == DB), `run()` returns `0` and the session status is `'closed'`.

- **R-014** [integration]: Backfill is only attempted when at least one stream has `gap > 0` (XDF count exceeds DB count). It is never attempted for negative gaps (DB > XDF).

- **R-015** [integration]: After backfill, reconciliation is re-run against the updated DB counts before `close_session` is called.

- **R-016** [integration]: When gaps remain after backfill, `run()` returns `1` and session status is `'failed'`.

- **R-017** [integration]: `write_reconciliation_log` is called for every run that reaches the reconciliation step, regardless of whether reconciliation succeeded or failed.

### ARC — integration tests

- **R-018** [integration]: When ARC config cannot be loaded, `run()` writes an `arc_failure` row to `alert_events`, closes the session as failed, and returns `1`.

- **R-019** [integration]: When `run_arc_post_session` raises `ARCPostSessionError`, `run()` writes an `arc_failure` row to `alert_events`, closes the session as failed, and returns `1`.

- **R-020** [integration]: `log_arc_failure_alert` opens its own DB connection independent of the main `conn` — alert write does not depend on the main connection's health.

### Resource cleanup — integration test

- **R-021** [integration]: The main DB connection is always closed in the `finally` block — no connection leak regardless of exit path.

## Won't Do

- Test XDF file format correctness — that belongs in the XDF writer spec.
- Test `close_session` or `run_backfill` internals — those belong in `batch.reconcile` specs.
- Test `run_arc_post_session` internals — that belongs in the ARC processor spec.
- Test the watchdog→session_close handoff sequence — end-to-end only.

## Risks

- **`settings.validate()` at module level** — importing `capture.session_close.workflow` without a valid `.env` raises `RuntimeError` at import time. Unlike `session_init` which validates inside `create_session()`, this makes the module harder to import in test environments. Mitigation for tests: mock `settings.validate` or ensure a valid `.env` / `TEST_DATABASE_URL` is present before importing.
- **ARC failure closes session as `failed` even when reconciliation succeeded** — accepted; ARC is a required post-session step; a session without ARC output is not considered complete.
- **`log_arc_failure_alert` failure is non-fatal** — accepted; if the alert write fails, it is logged but does not affect the session close outcome.

## Open Questions

- _(none)_
