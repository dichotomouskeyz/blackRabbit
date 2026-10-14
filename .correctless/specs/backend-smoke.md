# Synthetic backend smoke contract

- SM-001: Both smoke commands require matching DATABASE_URL and TEST_DATABASE_URL
  with an explicit test or audit database name before any connection or capture.
  Verify the connected database and current migration head before writes.
- SM-002: The offline smoke creates new synthetic identity and signals, retains
  its artifacts, and exercises capture, XDF recovery, verified closeout, separate
  ARC execution and deterministic replay. It never clears existing tables.
- SM-003: The LSL smoke uses distinct stream names, bounded process duration,
  orderly shutdown and cleanup, then checks XDF against database counts.
- SM-004: Receipts describe observed behavior and distinguish offline signal
  injection from actual local LSL transport. Neither establishes hardware or
  physiological interpretation quality.

Commands: `python -m scripts.backend_smoke --help` and
`python -m scripts.lsl_smoke --help`. Requires the migrated test database described
by the backend CI contract. Outputs are local and excluded from source control.
