# Spec: Forwarder

## Metadata
- **Task**: forwarder
- **Intensity**: standard
- **Recommended-intensity**: high (TB-002 overlap — LSL→DB write path)
- **Intensity reason**: TB-002 trust boundary fires; downgraded to standard for test-generation focus
- **Override**: lowered

## What

`capture/forwarder` reads live LSL streams for four modalities (EEG, HRV, EDA, respiration), writes each chunk to XDF backup first, then inserts rows into the corresponding TimescaleDB hypertable. One `StreamThread` runs per modality. Each thread resolves its LSL inlet, connects to the DB, and loops: pull chunk → XDF write → row-build → DB insert → integrity log → drift record. On DB connection loss, rows are buffered (up to `BUFFER_MAX_CHUNKS = 200`) and replayed when the connection recovers. `BUFFER_MAX_CHUNKS` is defined in `capture/forwarder/models.py` and is also importable from `capture.forwarder.stream_thread.stream_db` (the module that consumes it).

Each `StreamThread` owns its runtime resources: `thread.conn` (DB connection, `None` while down), `thread.inlet` (LSL inlet), and `thread.state` (`StreamThreadState`: buffer, sample_index, chunk_count, last_drift_ts, fatal_error). Helper signatures: `write_rows(thread, rows)`, `flush_buffer(thread)`, `maybe_record_drift(thread, now_lsl=None)` (see decisions.md "StreamThread Owns Its Runtime Resources"). Clock drift is recorded at a configurable interval; failure to write drift is fatal and triggers a clean shutdown of all threads so the watchdog can restart the process.

## Rules

### Release integrity contract (approved 2026-10-13)

- **R-021** [unit/integration]: Preflight loads canonical participant/site/sponsor
  identity and rejects any caller mismatch before opening XDF or starting workers.
- **R-022** [unit]: Missing required inlets, failed initial DB connection, and
  every ordinary worker exception retain a fatal error and set shared stop.
- **R-023** [unit]: An unexpectedly dead required worker or a join timeout makes
  the process fail. XDF may be finalized only after all writers have stopped.
- **R-024** [integration]: Capture owns the session advisory lock until all
  workers stop. A second capture or closeout must fail before changing state.
- **R-025** [integration]: Capture cannot resume a session that already has
  signal/marker rows or an XDF recording. The local MVP does not silently reset
  sample indices or append untracked capture segments; start a new session.
- **R-026** [unit]: All startup and runtime exits release resources. XDF write
  failures propagate before the corresponding DB write.

### Row builders — unit tests

- **R-001** [unit]: `build_eeg_rows` returns exactly one dict per channel in the sample (len(sample) rows).

- **R-002** [unit]: `build_eeg_rows` raises `ValueError` when `cfg.eeg_channel_names` is set and its length does not match `len(sample)`.

- **R-003** [unit]: `build_eeg_rows` falls back to `ch_0`, `ch_1`, ... channel names when `cfg.eeg_channel_names` is `None`.

- **R-004** [unit]: `build_eeg_rows` sets `lsl_timestamp` to the passed-in `lsl_ts` float — never wall clock.

- **R-005** [unit]: `build_hrv_rows` sets `heart_rate_bpm = None` when `rr_ms <= 0`.

- **R-006** [unit]: `build_hrv_rows` sets `heart_rate_bpm = 60000.0 / rr_ms` when `rr_ms > 0`.

- **R-007** [unit]: All four row builders (`build_eeg_rows`, `build_hrv_rows`, `build_eda_rows`, `build_respiration_rows`) include `session_id`, `participant_id`, `site_id`, and `sponsor_id` from `cfg` unchanged on every row.

- **R-008** [unit]: All four row builders include `lsl_timestamp` (the passed-in float) on every row.

- **R-009** [unit]: `build_rows` increments `thread._sample_index` by exactly 1 for each sample in the chunk, regardless of how many DB rows that sample expands to (EEG expands to N rows per sample, but `sample_index` increments once).

### SessionConfig — unit tests

- **R-010** [unit]: `SessionConfig.__post_init__` raises `ValueError` if any of `session_id`, `participant_id`, `site_id`, or `sponsor_id` is not a valid UUID string.

- **R-011** [unit]: `SessionConfig` is a frozen dataclass — fields cannot be mutated after construction.

### Chunk processing invariants — integration tests

- **R-012** [integration]: In `process_chunk`, XDF write (`xdf.write_samples`) is called before any DB write for the same chunk.

- **R-013** [integration]: After a successful chunk write, the rows appear in the correct modality table with the correct `session_id`, `lsl_timestamp`, and `sample_index` values.

- **R-014** [integration]: On `psycopg2.OperationalError` during `write_rows`, the rows are appended to the buffer and the connection is set to `None` (not lost silently without buffering).

- **R-015** [integration]: On a non-operational `psycopg2.Error` during `write_rows`, the transaction is rolled back and the connection is returned (not closed) — the thread continues.

- **R-016** [integration]: `flush_buffer` writes buffered chunks in FIFO order and removes each chunk from the buffer only after a successful write.

### Buffer overflow — unit test

- **R-017** [unit]: When `buffer_chunk` is called and the buffer is already at `BUFFER_MAX_CHUNKS`, the oldest chunk is dropped (deque overflow) and an error is logged with `dropped_rows` and `buffer_depth`.

### Clock drift — integration tests

- **R-018** [integration]: `maybe_record_drift` writes at most one drift row per `CLOCK_DRIFT_RECORD_INTERVAL` seconds per stream thread.

- **R-019** [integration]: `maybe_record_drift` raises `RuntimeError` when `conn` is `None` at the moment a drift write is due (not silently skipped).

- **R-020** [integration]: `run_stream_thread` catches that `RuntimeError`, logs at CRITICAL level, and sets `stop_event` so sibling threads wind down.

## Won't Do

- Test LSL stream resolution against real hardware or a live LSL outlet — use a mock or `pylsl.StreamInfo` stub.
- Test XDF file format correctness — that belongs in the XDF writer spec.
- Test the watchdog restart behavior — that belongs in the watchdog spec.
- Validate that `site_id` or `sponsor_id` exist in any reference table.

## Risks

- **Chunk silently dropped on non-operational DB error** (`psycopg2.Error` that is not `OperationalError`) — accepted; logged at ERROR level with row count; this is the deliberate design for constraint violations.
- **Buffer overflow loses oldest chunk** when `BUFFER_MAX_CHUNKS` is exceeded — accepted; logged at ERROR; MVP design trades bounded memory for possible sample loss during extended DB outages.
- **Clock drift write failure shuts down the forwarder** — accepted and intentional; the comment in `stream_runtime.py` explains this is preferable to running in a degraded state without drift records.

## Open Questions

- _(none)_
