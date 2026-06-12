# Spec: Watchdog

## Metadata
- **Task**: watchdog
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/watchdog` spawns `capture.lsl_forwarder` as a managed subprocess and keeps it alive during a session. On unexpected forwarder exit, the watchdog logs a `process_restart` alert, waits an exponentially-backed-off delay, and restarts the forwarder. After `MAX_RESTARTS = 5` consecutive crashes it stops restarting, sets session status to `'failed'`, and exits. On SIGTERM, the watchdog signals the forwarder to stop cleanly, waits for it, sets session status to `'closing'`, and exits — leaving `session_close` to run next.

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

- **R-007** [unit]: When `state.clean_shutdown` is `True` immediately after forwarder exit, `run_watchdog_loop` calls `handle_clean_shutdown` and does not increment `restart_count`.

- **R-008** [unit]: When the forwarder exits unexpectedly, `run_watchdog_loop` increments `restart_count` by 1 and calls `record_unexpected_exit` with the correct exit code and uptime.

- **R-009** [unit]: When `restart_count` exceeds `MAX_RESTARTS` after an unexpected exit, `run_watchdog_loop` calls `mark_session_failed` and exits the loop without further restarts.

- **R-010** [unit]: Every unexpected forwarder exit — including the exit that tips `restart_count` over `MAX_RESTARTS` — triggers a `log_restart` call. No crashes are silently skipped.

### Database writes — integration tests

- **R-011** [integration]: After an unexpected forwarder exit, `log_restart` writes exactly one row to `alert_events` with `alert_type = 'process_restart'`, `severity = 'warning'`, and `algorithm_parameters` containing the `exit_code`, `restart_count`, and `uptime_s` values.

- **R-012** [integration]: `alert_events` rows written by `log_restart` carry the correct tenancy (`session_id`, `participant_id`, `site_id`, `sponsor_id`).

- **R-013** [integration]: `mark_session_closing` sets session status to `'closing'` when status was `'active'`. It is idempotent — calling it when status is already `'closing'` affects 0 rows and does not raise.

- **R-014** [integration]: `mark_session_failed` sets session status to `'failed'` and sets `closed_at` when status is `'active'` or `'closing'`.

- **R-015** [integration]: `log_restart` failure (DB connection error or missing session) is non-fatal — the watchdog loop continues to the next restart despite the failure. (Note: this currently fails due to BUG-003 — `psycopg2.connect` and `lookup_compound` are outside the `try/except` block in `log_restart`.)

## Won't Do

- Test `stop_forwarder` against a real subprocess with real signal delivery — file-based IPC and OS signal behavior are OS-level concerns; test with a mock process.
- Test that `session_close` runs correctly after the watchdog exits — that is an end-to-end coordinator sequence, not a watchdog unit boundary.
- Test Windows-specific `CTRL_BREAK_EVENT` signal path separately from POSIX SIGTERM — conditional OS signal dispatch is OS-level behavior, not business logic.

## Risks

- **BUG-003** — `log_restart` in `capture/watchdog/db.py` calls `psycopg2.connect` and `lookup_compound` outside the `try/except` block (lines 51-52). A DB unavailability or missing session raises an unhandled exception that crashes the entire watchdog loop. `mark_session_closing` and `mark_session_failed` correctly put their connect calls inside the try — `log_restart` should match that pattern.
- **`log_restart`, `mark_session_closing`, `mark_session_failed` DB failures are non-fatal by design** — if the DB is unavailable when the forwarder crashes, the watchdog restarts the forwarder anyway. The unlogged restarts are acceptable loss; keeping the session alive takes priority.
- **`mark_session_closing` 0-row UPDATE on already-`'closing'` session is silent** — accepted; the downstream `session_close` is already set up to handle idempotent calls.

## Open Questions

- _(none)_
