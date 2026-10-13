# Spec: Session Close

## Metadata
- **Task**: session-close
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/session_close` verifies raw capture and closes the session. It obtains the shared session lock, validates canonical session and XDF identity, transitions an active session to `closing`, compares complete XDF and database sample counts, recovers positive gaps, and records the result. Successful close commits `closed` and the verified watermark. Analysis is a separate command. Exit codes are `0` for verified capture, `1` for reconciliation failure, and `2` for a failed precondition such as an unreadable file, identity mismatch, busy session, or invalid state.

`run()` accepts `xdf_path` as any path-like value (`str` or `pathlib.Path`) and coerces it to `Path` at entry — callers beyond the CLI (future UI/API) hand over string paths.

## Rules

### Release contract correction (approved 2026-10-13)

These rules supersede the previous ARC-in-close behavior and its accepted risk.
Closeout owns raw capture verification only; it never loads ARC configuration,
calls the processor, or changes capture validity because analysis failed.

- **R-018** [unit/integration]: Successful reconciliation closes capture and
  commits `watermark_verified` without calling ARC. Invalid ARC config cannot
  affect capture closeout.
- **R-019** [unit/integration]: Unexpected reconciliation failure rolls back and
  persists failed capture if the database remains reachable, returns 1, and
  never runs ARC. Terminal-state persistence failure must be observable.
- **R-020** [unit/integration]: Before any state change/backfill, closeout obtains
  the shared capture advisory lock and validates XDF session/participant/site/
  sponsor identity against the canonical row. Busy, wrong-identity, or malformed
  files return 2 without closing the session. Legacy XDF requires explicit opt-in.
- **R-022** [unit]: Import is side-effect free; runtime settings are validated
  at execution time. Every established connection closes on every path (R-021).

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

- **R-009** [integration]: `run()` returns `2` when the XDF file is unreadable, without changing session state or backfilling data.

- **R-010** [integration]: `run()` returns `2` when the session does not exist in `sessions` for the given `session_id` and `sponsor_id`.

- **R-011** [integration]: `run()` returns `2` when the session exists but is in a non-closeable state (`'closed'`, `'failed'`, `'initializing'`).

- **R-012** [integration]: `run()` logs a WARNING and transitions the session to `'closing'` when it is still `'active'` at call time, then continues.

### Reconciliation — integration tests

- **R-013** [integration]: When all stream counts match (XDF == DB), `run()` returns `0` and the session status is `'closed'`.

- **R-014** [integration]: Backfill is only attempted when at least one stream has `gap > 0` (XDF count exceeds DB count). It is never attempted for negative gaps (DB > XDF).

- **R-015** [integration]: After backfill, reconciliation is re-run against the updated DB counts before `close_session` is called.

- **R-016** [integration]: When gaps remain after backfill, `run()` returns `1` and session status is `'failed'`.

- **R-017** [integration]: `write_reconciliation_log` is called for every run that reaches the reconciliation step, regardless of whether reconciliation succeeded or failed.

### Analysis separation

See the release R-018/R-019/R-020 rules above. Analysis is a separate command
requiring verified capture; it cannot be invoked by this workflow.

### Resource cleanup — integration test

- **R-021** [integration]: The main DB connection is always closed in the `finally` block — no connection leak regardless of exit path.

## Won't Do

- Test XDF file format correctness — that belongs in the XDF writer spec.
- Test `close_session` or `run_backfill` internals — those belong in `batch.reconcile` specs.
- Test `run_arc_post_session` internals — that belongs in the ARC processor spec.
- Test the watchdog→session_close handoff sequence — end-to-end only.

## Risks

- If the database becomes unreachable, a terminal failure cannot be persisted. The command returns failure and logs the persistence error; it never reports a successful close.
- Legacy recordings require explicit recovery opt-in and remain unchanged on disk.

## Open Questions

- _(none)_
