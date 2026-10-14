# Spec: Watchdog

## Metadata
- **Task**: watchdog
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/watchdog` supervises one `capture.lsl_forwarder` subprocess. The local
MVP uses `MAX_RESTARTS = 0`: safe multi-segment resume is deferred, so unexpected
exit records the existing `process_restart` alert type, persists failure, and
returns nonzero without resetting sample indices. On requested shutdown, only
an exit code of zero may transition capture to `closing`. A requested shutdown
with a failed or killed child remains failed. Database terminal-state errors
propagate rather than reporting successful shutdown.

This release correction was approved on 2026-10-13. Backoff helpers remain compatibility
utilities; the release does not perform automatic restarts.

## Rules

### CLI parsing — unit tests

- **R-001** [unit]: `parse_uuid` raises `argparse.ArgumentTypeError` for any string that is not a valid UUID.

- **R-002** [unit]: `parse_uuid` accepts a valid UUID string and returns its canonical lowercase form.

### Forwarder command — unit test

- **R-003** [unit]: `build_forwarder_cmd` returns a list whose first three elements are `[sys.executable, "-m", "capture.lsl_forwarder"]` and whose remaining elements pass each UUID arg with its CLI flag (`--session-id`, `--participant-id`, `--site-id`, `--sponsor-id`).

### Restart backoff — unit tests

- **R-004** [unit]: `restart_delay_s(1)` returns `5.0`.

- **R-005** [unit]: `restart_delay_s` doubles on each increment: `restart_delay_s(2)` = `10.0`, `restart_delay_s(3)` = `20.0`.

- **R-006** [unit]: `restart_delay_s` is capped at `RESTART_DELAY_MAX_S` (60.0) — any `restart_count` that would exceed the cap returns exactly `60.0`.

### Watchdog loop — unit tests (mock subprocess + DB)

- **R-007** [unit]: A requested clean shutdown with child exit code zero calls `handle_clean_shutdown` without incrementing `restart_count`. A failed child is never marked closing.

- **R-008** [unit]: When the forwarder exits unexpectedly, `run_watchdog_loop` increments `restart_count` by 1 and calls `record_unexpected_exit` with the correct exit code and uptime.

- **R-009** [unit]: When `restart_count` exceeds `MAX_RESTARTS` after an unexpected exit, `run_watchdog_loop` calls `mark_session_failed` and exits the loop without further restarts.

- **R-010** [unit]: Every unexpected forwarder exit — including the exit that tips `restart_count` over `MAX_RESTARTS` — triggers a `log_restart` call. No crashes are silently skipped.

- **R-016** [unit]: `run_watchdog_loop` returns 0 only after persisted clean
  shutdown; unexpected child exit returns 1 and failed terminal persistence
  raises. The CLI propagates this outcome as its exit status.

### Database writes — integration tests

- **R-011** [integration]: After an unexpected forwarder exit, `log_restart` writes exactly one row to `alert_events` with `alert_type = 'process_restart'`, `severity = 'warning'`, and `algorithm_parameters` containing the `exit_code`, `restart_count`, and `uptime_s` values.

- **R-012** [integration]: `alert_events` rows written by `log_restart` carry the correct tenancy (`session_id`, `participant_id`, `site_id`, `sponsor_id`).

- **R-013** [integration]: `mark_session_closing` sets session status to `'closing'` when status was `'active'`. It is idempotent — calling it when status is already `'closing'` affects 0 rows and does not raise.

- **R-014** [integration]: `mark_session_failed` sets session status to `'failed'` and sets `closed_at` when status is `'active'` or `'closing'`.

- **R-015** [integration]: An alert-write failure is logged and does not prevent the watchdog from attempting to persist terminal session failure. Failure to persist that terminal state propagates; no restart is attempted.

## Won't Do

- Test `stop_forwarder` against a real subprocess with real signal delivery — file-based IPC and OS signal behavior are OS-level concerns; test with a mock process.
- Test that `session_close` runs correctly after the watchdog exits — that is an end-to-end coordinator sequence, not a watchdog unit boundary.
- Test Windows-specific `CTRL_BREAK_EVENT` signal path separately from POSIX SIGTERM — conditional OS signal dispatch is OS-level behavior, not business logic.

## Risks

- If the database is unavailable, neither the failure alert nor terminal state can be guaranteed. Terminal-state errors propagate to the caller.
- **`mark_session_closing` 0-row UPDATE on already-`'closing'` session is silent** — accepted; the downstream `session_close` is already set up to handle idempotent calls.

## Open Questions

- _(none)_
