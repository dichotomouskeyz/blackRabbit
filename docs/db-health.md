# Database Health & Hardening — `untitled_biometric_platform-1a`

**Repo:** `C:\Users\jahlo\untitled_biometric_platform-1a`
**Branch tracked:** `2R` (HEAD `b4d3111`)
**Doc started:** 2026-05-31
**Doc location:** tracked in repo at `docs/db-health.md`

A living tracker for the regulatory-grade DB invariants the platform depends on. Each section lists what the invariant is, the current state, evidence, and any open hardening items. Update the status column when something is verified or fixed.

**Status legend:** ✅ verified clean · ⚠️ partial / known caveat · ❌ broken / urgent · 📝 deferred / filed only · 🔍 needs re-verification

---

## At-a-glance status

| Area | Status | Last verified | Notes |
|---|---|---|---|
| Cursor / threading safety | ✅ | 2026-05-31 | No cross-thread cursor sharing in `capture/`. Each thread owns its own connection; cursors are transient. |
| SQL parameterization (capture/) | ✅ | 2026-05-31 | All SQL uses `%s` placeholders. `sql.Identifier` for table-name interpolation (hardened in `2dab714`). |
| SQL parameterization (batch/) | ✅ | 2026-05-31 | Same as above after `2dab714`. |
| Audit triggers (writes) | ✅ | 2026-05-31 | `audit_trigger_full_func()` in `020`; app code never directly INSERTs into `audit_events`. |
| Watermark trigger (gating) | ⚠️ | 2026-05-31 | Fires on `'closed'`/`'failed'` only — aborted sessions need separate handling (known issue, Phase 5b). |
| Tenancy enforcement (capture/) | ✅ | 2026-05-31 | All session-touching SELECTs/UPDATEs in `capture/` filter `AND sponsor_id = %s`. |
| Tenancy enforcement (batch/) | ⚠️ | 2026-05-31 | `batch/reconciliation/db.py:fetch_session_meta` (and `close_session` indirectly via meta) lack the filter — bugs.md LOW-01. |
| Migration chain integrity | ✅ | 2026-05-31 | `versions/` chain is internally complete (001→…→031). `optional_governance/` is a deliberate parallel tree, not walked by Alembic. |
| Up/down migration symmetry | ✅ | 2026-05-31 | Every migration spot-checked has a working `downgrade()`. |
| Pseudonymous IDs only | ✅ | 2026-05-31 | All `participant_id` columns are `UUID NOT NULL`. New `_FORBIDDEN_LOG_KEYS` guard in `capture/logger.py` strips name/email/dob/ssn/etc. from log payloads. |
| Transactional integrity: samples + integrity log | ⚠️ | 2026-05-31 | Two separate transactions. Window where `eeg_samples` is durable but `biosignal_integrity_log` row is missing. bugs.md MED-06 and MED-05 (buffer-flush path doesn't write integrity rows at all). |
| Reconciliation parity (XDF ↔ DB) | ✅ | 2026-05-31 | XDF written before DB row in `capture/forwarder/stream_thread/stream_chunks.py` (parallel write pattern). `capture/session_close/reconciliation.py` reconciles + backfills on close. |
| Tamper-evidence (biosignal chunks) | ⚠️ | 2026-05-31 | `biosignal_integrity_log` (migration 026) carries MD5 chunk hash. Honest about boundaries (not used for security — `usedforsecurity=False`). Gap: buffer-flush path (MED-05) and separate-transaction window (MED-06). |
| Connection pooling | n/a | 2026-05-31 | No pool in use. Each thread/operation opens its own connection. Acceptable for current scale (≤5 capture threads + watchdog). |
| Cursor leak on exception path | ⚠️ | 2026-05-31 | `stream_db.write_rows` and `stream_integrity.write_integrity_log` use raw `cur = conn.cursor()` / `cur.close()` instead of `with conn.cursor() as cur:`. Intra-thread leak on exception until GC. |

---

## 1. Cursor / threading safety  ✅

**Invariant:** psycopg2 connections are thread-safe; cursors are NOT. No cursor may be shared across threads.

**Verified pattern:**

| Thread | Connection | Cursor pattern |
|---|---|---|
| `StreamThread` (one per modality) | `thread.connect_db()` inside `run()` → fresh `psycopg2.connect()` (`capture/forwarder/stream_thread/stream_db.py:12-15`). | `write_rows`: local `cur = conn.cursor()` → `execute_batch` → `cur.close()` (`stream_db.py:49-52`). `write_integrity_log`: same (`stream_integrity.py:24-45`). `maybe_record_drift`: `with conn.cursor() as cur:` (`stream_drift.py:39-54`). |
| `ECHOThread` | `thread.connect_db()` → fresh `psycopg2.connect()` (`capture/echo_handler/db.py:35-50`). | `db.write_row`: `with conn.cursor() as cur:` (`echo_handler/db.py:70-71`). |
| Forwarder main thread | Holds no DB connection during capture. | n/a |
| `preflight` (pre-thread, main) | Local connection in `with` blocks (`capture/forwarder/preflight.py:15-56, 60-93`). | `with conn.cursor() as cur:` (cleanest pattern). |
| `session_init`, `session_close`, `watchdog` | Sequential main-thread code. | Local cursor per op. |

**Cross-checks:**
- `Grep` for `self._cur | thread._cur | self._conn | thread._conn` across `capture/` → 0 matches. Connections/cursors are never stashed on instance state, so there's no path for a second thread to reach into another thread's cursor.
- `Grep` for `psycopg2.connect | psycopg2.pool` → 12 call sites, every one owns its connection's lifecycle locally. No shared pool.

**Open:** the intra-thread cursor-leak case noted in section 14 below.

---

## 2. SQL parameterization  ✅

**Invariant:** No SQL value is interpolated via f-string or `.format()`. Values bind via `%s` (psycopg2) or named placeholders. Identifiers (table/column names) that vary use `psycopg2.sql.Identifier`.

**State (post `2dab714` security commit):**
- `batch/arc/processor.py:_query_biosignal_count` — `sql.SQL(...).format(table_name=sql.Identifier(table_name))` for the table name; values still bind via `%s`.
- `batch/reconciliation/db.py:query_db_counts` + `fetch_existing_sample_indices` — same `sql.Identifier` pattern.
- All `capture/**/sql.py` modules — pure string templates with `%s` placeholders; no interpolation. SQL is centralized per submodule (forwarder, session_init, session_close, echo_handler).
- ARC processor + watchdog audit triggers — DO blocks in migrations (Postgres-side), not application-built SQL.

**Open:** none.

---

## 3. Audit trail integrity (triggers-only writes)  ✅

**Invariant:** Application code MUST NOT INSERT directly into `audit_events`. Database triggers own audit row creation.

**Trigger function:** `audit_trigger_full_func()` (migration `020_audit_triggers.py:73-103`). Uses PL/pgSQL `IF/ELSE` on `TG_TABLE_NAME` (lazy evaluation — avoids SQL CASE's all-branch evaluation bug that would crash on tables without `session_id`).

**Tables under full audit (one audit row per INSERT):**
`sessions`, `alert_events`, `echo_events`, `session_feature_vectors`, `session_notes`, `schema_version_log`, `session_signal_metadata`.

**Tables intentionally excluded:** the four biosignal hypertables (eeg/hrv/eda/respiration) — high-volume, would generate millions of audit rows per long session. They use `biosignal_integrity_log` (migration 026) for chunk-level provenance instead. See section 9.

**Verification command:**
```
grep -rn "INSERT INTO audit_events" capture/ batch/ ingestion/ storage/ src/
```
(should produce 0 matches in application code — only migrations should contain it).

**Open:** none. The CLAUDE.md "Known Issues" item about `audit_trigger_smart_func` matching the live DB is a deployment-side check, not a code change.

---

## 4. Watermark gating  ⚠️

**Invariant:** Batch jobs must only fire after `watermark_verified` is written to `audit_events`. Watermark events come from a DB trigger, never the application.

**Trigger function:** `sessions_watermark_func()` (migration `024_watermark_trigger.py:25-102`). Fires `AFTER UPDATE ON sessions FOR EACH ROW` only on genuine status transitions (`NEW.status != OLD.status`).

| Status transition | Event written |
|---|---|
| → `'closed'` | `'session_status_transition'` + `'watermark_verified'` |
| → `'failed'` | `'session_status_transition'` + `'watermark_failed'` |
| any other | `'session_status_transition'` only |

**Known caveat (CLAUDE.md "Known Issues" #2, deferred to Phase 5b):** aborted sessions (dose administered, session aborted) are clinically significant under ITT analysis but currently never reach `'closed'` or `'failed'` — they need a separate watermark path. Not a code bug; an explicitly deferred design item.

**Open:**
- Aborted-session watermark path (Phase 5b scope).
- `capture/session_close/workflow.py` can leave a session pinned in `'closing'` if `reconcile_session` raises (bugs.md MED-04), in which case no terminal status is written and no watermark fires. Recommended fix: wrap reconciliation in try/except and explicitly set status to `'failed'` on unexpected error.

---

## 5. Tenancy enforcement (sponsor_id / site_id)  ⚠️

**Invariant:** Every query against a session-scoped table filters `AND sponsor_id = %s` (and `site_id` where applicable). No exceptions on patient-touching reads/writes.

**Coverage in `capture/`:**

| Site | Status |
|---|---|
| `capture/watchdog/db.py:21, 105, 130` | ✅ all three SELECT/UPDATE filter `sponsor_id` |
| `capture/forwarder/preflight.py:19, 43, 68` | ✅ all three filter `sponsor_id` |
| `capture/session_close/db.py:32, 50, 70` | ✅ all three filter `sponsor_id` |
| `capture/session_init/sql.py`, `workflow.py` | ✅ INSERTs include `sponsor_id` column on every row; pre-flight reads filter `sponsor_id` |
| `capture/echo_handler/db.py:write_row` | ✅ row carries `sponsor_id`; ECHO is a write-only path |

**Coverage in `batch/`:**

| Site | Status |
|---|---|
| `batch/reconciliation/db.py:fetch_session_meta` (line 125) | ❌ `WHERE id = %s` only — no sponsor_id filter (bugs.md LOW-01). |
| `batch/reconciliation/db.py:close_session` (line 79) | ⚠️ Calls `fetch_session_meta` internally, so inherits the LOW-01 gap; the row-write itself includes sponsor_id but the read doesn't validate it. |
| `batch/reconciliation/db.py:query_db_counts`, `fetch_existing_sample_indices` | n/a — these are counts/reads scoped to a session UUID for reconciliation, not per-row patient reads. Consider adding sponsor_id as a defensive filter when Phase 4 wires through. |

**Open:**
- bugs.md LOW-01: add sponsor_id parameter + WHERE clause to `fetch_session_meta` and propagate through `close_session`. Callers already have `sponsor_id` on hand (session_close passes it). Estimated fix: 5 lines.

---

## 6. Migration chain integrity  ✅

**Invariant:** Alembic's `down_revision` chain is unbroken from `None` (the root) to the head. No two revisions share a `down_revision` (would create a branch).

**Active chain (`versions/`):**
```
001_extensions
  → 002_sessions
  → 003_compound_reference
  → 004_eeg_samples
  → 005_hrv_samples
  → 006_eda_samples
  → 007_respiration_samples
  → 008_audit_events
  → 009_alert_events
  → 010_echo_events
  → 011_pgvector_columns
  → 012_compression
  → 013_compression_policy
  → 015_schema_version_metadata          (skips 014)
  → 019_session_signal_metadata          (skips 016, 017, 018)
  → 020_audit_triggers
  → 021_correction_amendment_log
  → 022_session_environment_log
  → 023_indexes
  → 024_watermark_trigger
  → 025_clock_drift_log
  → 026_biosignal_integrity_log
  → 027_session_baselines
  → 028_event_composite_profiles
  → 029_echo_events_manual_marker
  → 030_arc_failure_alert_type
  → 031_capture_mode_fields
```

The numbering gap (014, 016, 017, 018) is intentional: those four migrations live in `untitledplatform_1a_db/db/alembic/optional_governance/` and form a parallel chain rooted at `013_compression_policy`:
```
014_consent_log
  → 016_electronic_signatures
  → 017_investigational_product_log
  → 018_adverse_event_log
```

**Why this is safe:** `alembic.ini:7` declares `script_location = untitledplatform_1a_db/db/alembic`. Alembic walks `script_location/versions/` only — `optional_governance/` is NOT discovered on `upgrade head`. Regulated deployments that need Part 11 governance can wire up `optional_governance/` separately. The MVP never sees those migrations.

**Verification command:**
```
cd untitledplatform_1a_db/db/alembic && alembic history --verbose
```
(should show a single linear chain 001 → 031).

**Open:** none. If `optional_governance/` is ever activated, the `015` migration's `down_revision = "013_compression_policy"` will collide with `014_consent_log`'s `down_revision = "013_compression_policy"` — that's a branch. At that point, `014_consent_log` would need its `down_revision` chained from `013` and `015_schema_version_metadata` chained from `014_consent_log` instead.

---

## 7. Up/down migration symmetry  ✅

**Invariant:** Every migration has a `downgrade()` that is the precise inverse of `upgrade()`. Rolling back should leave the schema in the state it was in pre-migration.

**Spot-checks performed:**
- `020_audit_triggers.py:115-118` — `downgrade()` drops each trigger and the function. ✓
- `024_watermark_trigger.py:112-114` — drops trigger then function. ✓
- `030_arc_failure_alert_type.py:43-59` — drops the new constraint, re-adds the prior 6-value CHECK. ✓
- `031_capture_mode_fields.py:37-39` — drops the two added columns. ✓

**Open:** full pass across 001–031 not done yet. Filed under 🔍.

---

## 8. Pseudonymous IDs only  ✅

**Invariant:** No real PII appears anywhere in the DB or in logs. Only pseudonymous UUID `participant_id` tokens are persisted.

**Schema enforcement:** `participant_id UUID NOT NULL` on every table that carries it (sessions, eeg_samples, hrv_samples, eda_samples, respiration_samples, echo_events, alert_events, session_signal_metadata, clock_drift_log, biosignal_integrity_log, session_baselines, event_composite_profiles, session_feature_vectors). The DB rejects non-UUID values.

**Logger enforcement (post `2dab714`):** `capture/logger.py:_FORBIDDEN_LOG_KEYS` is a frozenset of `{address, api_key, date_of_birth, dob, email, name, participant_name, password, phone, secret, ssn, token}`. The JSON formatter drops these keys from log `extra` payloads at serialization time. Even if a caller accidentally passes `extra={"email": "..."}`, it never reaches stdout or the log file.

**XDF enforcement (post `2dab714`):** every user-controlled value written to the XDF stream-header XML is passed through `html.escape()` to prevent XML injection if a tokenized ID ever contains `<`, `>`, or `&`.

**Known caveat (CLAUDE.md "Known Issues" #4):** `row_to_json(NEW)::jsonb` in the audit trigger function copies the entire row including any future PII column. Safe today because all current columns are pseudonymous. If a real-PII column is ever added, the audit trigger needs JSONB `-` exclusion before it runs.

**Open:** none today. Re-verify if any new column is added to a trigger-watched table.

---

## 9. Transactional integrity: samples + integrity log  ⚠️

**Invariant:** A biosignal sample chunk and its corresponding `biosignal_integrity_log` row should be visible atomically — either both present or both absent. Tamper-evidence requires the chunk-hash record to track every chunk durably written.

**Current state (broken on two paths):**

1. **Separate transactions (bugs.md MED-06):** `stream_db.write_rows` commits the sample INSERT at `stream_db.py:51`, then `stream_integrity.write_integrity_log` runs and commits the integrity row separately at `stream_integrity.py:44`. If the integrity INSERT fails (deadlock, transient error), the samples are durable but no chunk_hash row exists. Tamper-evidence has a hole at exactly the boundary where it matters most.
2. **Buffer-flush path (bugs.md MED-05):** `stream_chunks.write_rows_and_integrity` calls `flush_buffer(conn)` first to drain older buffered chunks, then writes the current chunk + integrity row. Buffered chunks that get re-written via `flush_buffer` have **no `biosignal_integrity_log` row** ever written for them — the chunk-hash record is missing for any chunk that survived a DB drop. Reconciliation at session_close compares DB row count vs XDF row count and likely matches, but the chunk-level integrity audit will have holes corresponding exactly to the DB-unavailability window.

**Recommended fix (both paths):**
- Combine into one transaction: append the integrity INSERT to the sample-write transaction in `stream_db.write_rows` so a single commit covers both.
- In `flush_buffer` (`stream_db.py:88-104`), also call `thread.write_integrity_log(conn, rows)` after each successful chunk write. Match the live-write path exactly.

**Open:** MED-05 + MED-06 filed in bugs.md. Held for the "final Phase 2" branch.

---

## 10. Reconciliation parity (XDF ↔ DB)  ✅

**Invariant:** Every biosignal sample written to the DB is also written to the XDF backup. XDF is the reconciliation source of truth if a DB write fails.

**Current state:**
- The forwarder writes XDF **first**, then DB (parallel write pattern in `capture/forwarder/stream_thread/stream_chunks.py`).
- `XDFWriter` (`capture/xdf/writer.py:60`) has its own `threading.Lock`, so concurrent writes from all stream threads serialize at the file level — no torn writes.
- On session close, `capture/session_close/reconciliation.py` → `batch/reconcile.py` → `batch/reconciliation/db.py:query_db_counts` + `batch/reconciliation/xdf.py:read_xdf_counts` → reconcile + backfill any gap from XDF.

**Open hardening (bugs.md MED-09):**
- XDF write failures are logged but never escalate to the watchdog or operator. If XDF writes fail repeatedly (disk full, FS error, permissions lost mid-session), reconciliation at session_close will report a non-zero gap but have **no ground truth to backfill from**. Recommend adding a `write_failure_count` counter on `XDFWriter` and a watchdog escalation path.

---

## 11. Tamper-evidence (biosignal chunks)  ⚠️

**Invariant:** Every biosignal chunk has a hash record in `biosignal_integrity_log` (migration 026). Replay/forensics can compare a recomputed hash against the stored one.

**Current state:**
- Hash method: MD5 over JSON-sorted chunk fields (`stream_integrity.py:18-22`). Marked `usedforsecurity=False` — used for completeness/replay, not as a security primitive.
- Sort keys + hash fields are per-modality (`thread._hash_fields`, `thread._hash_sort_keys`, set per-stream in `streams.py`).
- Reconciliation + backfill use the integrity log to detect gaps.

**Open:** see section 9 — gaps during buffer-flush and on the separate-transaction window. These directly compromise tamper-evidence on exactly the failure modes it was designed to cover.

---

## 12. Connection lifecycle (open / close / reconnect)  ✅

**Invariant:** Every connection that's opened is eventually closed. Reconnection on transient failure is bounded by exponential backoff. The shutdown path always closes connections.

**Current state:**
- `stream_db.connect_db` (lines 18-32) and `echo_handler/db.connect_db` (lines 35-50) both use exponential backoff (1s → 30s cap) gated by `stop_event.wait()` so SIGTERM unblocks them immediately.
- `stream_runtime._run_stream_thread_inner` (post `b4d3111`) uses `try: ... finally:` to guarantee `conn.close()` even if the loop exits via exception. Same for `_run_stream_thread_inner`'s outer wrapper (`run_stream_thread`).
- `preflight.py` and `session_close/db.py` use `try: ... finally: conn.close()` consistently.

**Open hardening (bugs.md MED-03):** `capture/watchdog/db.py:log_restart` leaks the connection if `lookup_compound` raises **before** the `try:` block at line 53. Fix: move `lookup_compound` inside the `try` block. Filed in bugs.md MED-03.

---

## 13. Error handling at the DB boundary  ⚠️

**Invariant:** Transient DB errors (OperationalError, deadlock, serialization failure) should buffer for retry. Non-transient errors (DataError, IntegrityError) should rollback and report.

**Current state:**
- **Connection-down (`psycopg2.OperationalError`):** ✅ Buffered into `thread.buffer` (deque, maxlen `BUFFER_MAX_CHUNKS=200`). Reconnect on next loop iteration. Same pattern in `stream_db.py:54-61` and `echo_handler/db.py:90-96`.
- **Other `psycopg2.Error`:** ⚠️ Currently treated as permanent drop. Deadlock and SerializationFailure should be retried but are dropped silently with a log line. bugs.md MED-07 (biosignal) + LOW-04 (ECHO).

**Open hardening:**
- Catch `psycopg2.errors.DeadlockDetected` and `SerializationFailure` explicitly and treat as transient (append to `thread.buffer` for retry). Only truly fatal errors (DataError after the row builder ran) should drop the chunk permanently, and those should log at ERROR with the row payload.

---

## 14. Cursor leak on exception path  ⚠️

**Invariant (smaller-stakes hygiene):** A cursor should always be closed, even when the SQL raises. The `with conn.cursor() as cur:` form does this for free.

**Current state:**
- `stream_db.py:49-52` uses raw `cur = conn.cursor()` / `cur.close()` after `conn.commit()`. If `execute_batch` raises, the cursor leaks until GC. Connection is still safe (the `except` branches rollback and either reuse or close it).
- `stream_integrity.py:24-45` has the same pattern.
- `preflight.py`, `echo_handler/db.py`, `session_close/db.py` use the `with` form throughout — fine.

**Recommended fix:** convert the two raw-cursor sites to `with conn.cursor() as cur:`. ~3 lines each, no behavior change on the happy path, deterministic close on the exception path.

**Open:** not in bugs.md; added here as a tracked item. Low priority but trivial fix.

---

## 15. Schema documentation accuracy  ✅

**Invariant:** `untitledplatform_1a_db/db/SCHEMA.md` reflects the actual migration state. Drift between the doc and the migrations is itself a tamper-evidence risk (an auditor would see the doc, not the migration).

**Recent updates (commit `b269df7`):**
- `eda_samples.conductance_us` and `respiration_samples.processed_amplitude` re-documented as "currently a pass-through copy of raw" instead of the misleading "after software_filters".
- `device_type` column moved from `session_baselines` documentation to `session_signal_metadata` (matches migration `031`).
- `echo_events.actor_id` documented as nullable.
- Stale "MNE/Neurokit2" claim on `session_feature_vectors` removed.

**Open:** full SCHEMA.md ↔ migration cross-check across 001–031 still pending. Filed under 🔍.

---

## Open items rollup (single source of truth for follow-up)

| # | Area | Severity | Source | Status |
|---|---|---|---|---|
| 1 | Aborted-session watermark path | Design / Phase 5b | CLAUDE.md known issue #2 | 📝 deferred |
| 2 | `session_close` stuck in `'closing'` on reconciliation failure | Bug | bugs.md MED-04 | 📝 filed |
| 3 | `batch/reconciliation/db.py:fetch_session_meta` missing sponsor_id | Tenancy hardening | bugs.md LOW-01 | 📝 filed |
| 4 | `versions/` ↔ `optional_governance/` future activation collision | Design note | this doc | 🔍 known, documented |
| 5 | Integrity log written in separate transaction from samples | Tamper-evidence gap | bugs.md MED-06 | 📝 filed |
| 6 | Integrity log NOT written during buffer-flush path | Tamper-evidence gap | bugs.md MED-05 | 📝 filed |
| 7 | XDF write-failure visibility | Reconciliation safety | bugs.md MED-09 | 📝 filed |
| 8 | `watchdog.db.log_restart` connection leak | Resource hygiene | bugs.md MED-03 | 📝 filed |
| 9 | psycopg2.Error path drops chunks instead of retrying deadlock/serialization | Error handling | bugs.md MED-07 (biosignal) + LOW-04 (ECHO) | 📝 filed |
| 10 | Cursor leak on exception (raw `cur = conn.cursor()` form) | Hygiene | this doc §14 | 📝 new |
| 11 | Full SCHEMA.md ↔ migration cross-check (001–031) | Doc drift sweep | this doc §15 | 🔍 pending |
| 12 | `audit_trigger_smart_func` matches live DB (COALESCE + TG_TABLE_NAME + NULL handler) | Deployment | CLAUDE.md known issue #3 | 🔍 deployment-side |
| 13 | `row_to_json` PII exclusion if any real-PII column ever lands | Future-proofing | CLAUDE.md known issue #4 | 🔍 conditional |
| 14 | Hypertable compression + backfill procedure documented | Operational doc | CLAUDE.md known issue #5 | 📝 deferred |

---

## Verification log

| Date | Verified by | Item | Result |
|---|---|---|---|
| 2026-05-31 | Claude Opus 4.7 (local session) | Cross-thread cursor sharing across `capture/` | No instances found. `Grep` for instance-stashed conn/cursor + cross-reference of every threaded entity. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Migration chain integrity (versions/) | Unbroken 001 → 031 chain. `optional_governance/` is a deliberate parallel tree not walked by Alembic. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Tenancy filter coverage in `capture/` | All 9 session-touching SELECT/UPDATE sites confirmed to include `AND sponsor_id = %s`. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Audit trigger function (020) | Function definition matches CLAUDE.md description. PL/pgSQL IF/ELSE on `TG_TABLE_NAME` (avoids SQL CASE eager-eval bug). |
| 2026-05-31 | Claude Opus 4.7 (local session) | Watermark trigger function (024) | Fires only on `NEW.status != OLD.status`. `'closed'` → `watermark_verified`, `'failed'` → `watermark_failed`. |
| 2026-05-29 | Ultraplan cloud session | bugs.md report | Produced full file-by-file bug review with 2C/1H/12M/9L/4I findings. |
| 2026-05-29 | Local session | bugs.md HIGH-01 fix | `b4d3111`: `run_stream_thread` catches RuntimeError, sets stop_event, logs CRITICAL. 65 tests pass. |
| 2026-05-29 | Local session | session_close imports clean | `uv run python -m capture.session_close --help` succeeds — both Criticals from bugs.md pre-resolved. |
| 2026-05-29 | Ultraplan cloud session | `2dab714 fix(security): harden metadata logging and static checks` | PII guard in logger, HTML escape in XDF metadata, `sql.Identifier` for dynamic table names. |

---

## How to update this doc

When you fix or verify something:

1. Update the **status column** in the at-a-glance table (✅ / ⚠️ / ❌ / 📝 / 🔍).
2. Update the **"Last verified" date** in that row.
3. Add a new row to the **Verification log** at the bottom with what you did and the result.
4. If a fix lands, remove or strikethrough the corresponding entry in the **Open items rollup**.
5. If a new invariant emerges (e.g., new module, new contract), add a section here with the same shape: Invariant / Current state / Open.

This doc is tracked in-repo so it travels with the branch and is visible to anyone who clones. When you cut the "final Phase 2" branch, carry the verification log forward — don't reset it. The repo is private; deployment will go to a separate public repo, so review/health content here is intentional and safe to commit.
