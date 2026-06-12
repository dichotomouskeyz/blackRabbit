# Database Health & Hardening — `untitled_biometric_platform-1a`

**Repo:** `C:\Users\jahlo\untitled_biometric_platform-1a`
**Branch tracked:** `2R`
**Doc started:** 2026-05-31 · **Restructured:** 2026-05-31
**Doc location:** tracked in repo at `docs/2R/db-health.md`

A study artifact + living tracker. Each section pairs an abstract database concept (the kind a backend developer needs to recognize cold) with how that concept lives in *this* pipeline (with `file:line` evidence). Sections are organized into 5 tiers — fundamentals first, operational concerns last — so the doc has a learning progression.

**Section template (every section uses the same shape):**

```
## §X.Y <Concept name>  <status emoji>

**Concept.** Textbook definition. No project-specific content.
**In this pipeline.** How it shows up here, with file:line.
**Status.** One sentence + emoji.
**Open.** Items to fix / learn / decide.
```

**Status legend:** ✅ verified clean · ⚠️ partial / known caveat · ❌ broken / urgent · 📝 deferred / filed only · 🔍 needs re-verification · `n/a` not applicable today by design

---

## At-a-glance — by tier

### Tier 1 — Foundations (textbook DB concepts every backend dev needs)

| § | Concept | Status | Last verified | One-line |
|---|---|---|---|---|
| 1.1 | Connection lifecycle | ✅ | 2026-05-31 | Each thread/op opens its own connection; `try/finally` close everywhere. |
| 1.2 | Connection pooling | `n/a` | 2026-05-31 | No pool by design — small thread count (≤5 capture threads + watchdog). Threshold to revisit is roughly ~10 concurrent connections. |
| 1.3 | Transactions & isolation level | ✅ | 2026-05-31 | `autocommit = False` + Postgres default **READ COMMITTED**. Documented as the contract. |
| 1.4 | SQL injection / parameterization | ✅ | 2026-05-31 | Every value binds via `%s` placeholders. `psycopg2.sql.Identifier` for dynamic table names (hardened in `2dab714`). |
| 1.5 | Constraints (PK / FK / UNIQUE / CHECK / NOT NULL) | ⚠️ | 2026-05-31 | CHECK + NOT NULL coverage strong. UNIQUE gap on `echo_events` + `biosignal_integrity_log` natural keys. |
| 1.6 | Indexes | ✅ | 2026-05-31 | `023_indexes.py` covers all core tables; later migrations (025–028) add their own. EXPLAIN ANALYZE spot-check pending real data. |
| 1.7 | Migrations & schema chain | ✅ | 2026-06-11 | `versions/` chain unbroken 001 → 030. `optional_governance/` is a deliberate parallel tree. Up/down symmetry spot-checked. |

### Tier 2 — Concurrency (once threads enter the picture)

| § | Concept | Status | Last verified | One-line |
|---|---|---|---|---|
| 2.1 | Cursor / thread safety | ✅ | 2026-05-31 | Connections are thread-safe; cursors aren't. No cursor is ever shared across threads here. |
| 2.2 | Threading model in this pipeline | ✅ | 2026-05-31 | 4 `StreamThread`s + 1 `ECHOThread` per forwarder. `XDFWriter.threading.Lock` + `stop_event` are the only shared sync primitives. |
| 2.3 | Deadlock + serialization retry | ⚠️ | 2026-05-31 | `OperationalError` is buffered for retry; other `psycopg2.Error` (including deadlocks) is dropped silently — bugs.md MED-07 / LOW-04. |
| 2.4 | Cursor leak on exception | ⚠️ | 2026-05-31 | Two sites use raw `cur = conn.cursor()` / `cur.close()` instead of `with`. Intra-thread leak on exception until GC. |

### Tier 3 — Domain integrity (the clinical-grade audit story)

| § | Concept | Status | Last verified | One-line |
|---|---|---|---|---|
| 3.1 | Audit trail (triggers-only writes) | ✅ | 2026-05-31 | `audit_trigger_full_func()` in migration 020. App code never inserts into `audit_events`. |
| 3.2 | Watermark gating | ⚠️ | 2026-05-31 | Fires on `'closed'` → `watermark_verified`, `'failed'` → `watermark_failed`. Aborted sessions are an explicit Phase 5b deferral. |
| 3.3 | Tamper-evidence (chunk hashes) | ⚠️ | 2026-05-31 | `biosignal_integrity_log` (migration 026, MD5 chunk hash). Gaps: buffer-flush path (MED-05) + separate-transaction window (MED-06). |
| 3.4 | XDF ↔ DB reconciliation parity | ✅ | 2026-05-31 | XDF written *before* DB row. `capture/session_close/reconciliation.py` reconciles + backfills on close. |
| 3.5 | Tenancy enforcement (`sponsor_id` / `site_id`) | ⚠️ | 2026-05-31 | `capture/` covered. `batch/reconciliation/db.py:fetch_session_meta` is missing the filter — bugs.md LOW-01. |
| 3.6 | Pseudonymous IDs | ✅ | 2026-05-31 | All `participant_id` columns are `UUID NOT NULL`. PII log guard in `capture/logger.py:_FORBIDDEN_LOG_KEYS`. |
| 3.7 | Two-timestamp invariant (`lsl_timestamp` vs `db_insert_time`) | ✅ | 2026-05-31 | Always distinct, never derived from each other. `lsl_timestamp` is `DOUBLE PRECISION` (epoch); `db_insert_time` is `TIMESTAMPTZ`. |
| 3.8 | Timezone consistency | ✅ | 2026-05-31 | All persisted timestamps `TIMESTAMPTZ NOT NULL DEFAULT NOW()`. Zero naive `datetime.now()` in `capture/`. |

### Tier 4 — TimescaleDB specifics

| § | Concept | Status | Last verified | One-line |
|---|---|---|---|---|
| 4.1 | Hypertable chunk sizing | ✅ | 2026-05-31 | All 4 biosignal hypertables use `chunk_time_interval = INTERVAL '1 hour'` on `db_insert_time`. |
| 4.2 | Compression policy | ✅ | 2026-05-31 | Auto-compress chunks older than 1 day (migration 013). `segmentby = (session_id, channel_id\|device_id)`, `orderby = lsl_timestamp DESC`. |
| 4.3 | Continuous aggregates | 📝 | 2026-05-31 | Not used today. ARC batch could materialize per-minute HRV/EDA aggregates later. Deferred. |
| 4.4 | Retention policy | 📝 | 2026-05-31 | None set. Old session chunks live forever. Acceptable for local-research MVP; revisit in a regulated deployment. |

### Tier 5 — Operational / deployment (decisions you'll document for prod)

| § | Concept | Status | Last verified | One-line |
|---|---|---|---|---|
| 5.1 | DB role / privilege architecture | ❌ | 2026-05-31 | Single superuser today. CLAUDE.md known issue #1 — required before UCSF deployment. |

### Tier 6 — Spec-vs-implementation compliance (findings from spec-driven TDD, 2026-06-09)

| § | Concept | Status | Last verified | One-line |
|---|---|---|---|---|
| 6.1 | `create_session` pre-DB input validation | ✅ | 2026-06-11 | Validation now runs before the DB connection for compound, participant UUID, and dose unit. |
| 6.2 | Proposed `capture_source` → `capture_mode` rename | ✅ | 2026-06-11 | The uncommitted rename was reverted; schema and runtime consistently use `capture_source` / `CAPTURE_SOURCE`. |
| 6.3 | `StreamResult` / `ReconciliationReport` computed vs stored fields | ✅ | 2026-06-09 | `gap` and `is_reconciled` are stored fields; `build_report` owns the computation. Integration R-015 covers it. |
| 6.4 | `centered_arc_window` empty-dict fallback | ✅ | 2026-06-09 | Empty `widths_s` falls back to canonical defaults; only a non-empty dict missing a key raises. |

| 5.2 | TLS in transit | ⚠️ | 2026-05-31 | DSN has no `sslmode=` — defaults to libpq `prefer`. Fine for localhost Docker; must be `require`+ for any remote target. |
| 5.3 | Secrets management for `DATABASE_URL` | ✅ | 2026-05-31 | `.env` + `python-dotenv` + `.gitignore` + pre-commit `no-env-files` hook. No rotation story yet. |
| 5.4 | Backup / DR | ⚠️ | 2026-05-31 | XDF parallel backup covers biosignals only. `audit_events`, `sessions`, integrity logs have no application-level backup. No PITR. |
| 5.5 | Disk capacity / data growth | ⚠️ | 2026-05-31 | ~600 MB compressed per 4 h session (per migration 012 design note). No monitoring, no alert. |
| 5.6 | Failure recovery procedures | ⚠️ | 2026-05-31 | Process crash → watchdog restart. DB crash → reconcile from XDF on close. Disk loss → undefined. |
| 5.7 | Trigger firing order | ✅ | 2026-05-31 | `sessions` has audit (INSERT) + watermark (UPDATE) triggers — different events, no collision. Documented for future-Jay. |
| 5.8 | Schema version visibility at runtime | ⚠️ | 2026-06-07 | `schema_version_log` population implemented in `capture.session_init`; follow-up tests still need to be written. Startup-time schema compatibility check remains open. |

---

## Tier 1 — Foundations

### §1.1 Connection lifecycle  ✅

**Concept.** A database connection is a long-lived TCP session + server-side resources (memory, query plans, locks). Every connection opened must eventually be closed; the close must happen even on exceptions, otherwise the server accumulates dead connections until it hits `max_connections` and refuses new clients. Pattern: `try: ... finally: conn.close()`. Reconnects on transient failure should back off (exponential) so a flapping DB doesn't get DoSed by retries.

**In this pipeline.**
- `capture/forwarder/stream_thread/stream_db.py:12-15` opens `psycopg2.connect(settings.DATABASE_URL)` inside each `StreamThread.run()` loop. Same pattern in `capture/echo_handler/db.py:35-50`.
- Reconnect uses exponential backoff (1 s → 30 s cap) gated by `stop_event.wait(backoff)` so SIGTERM unblocks immediately. See `stream_db.connect_db:18-32`.
- `capture/forwarder/stream_thread/stream_runtime.py:_run_stream_thread_inner` (post `b4d3111`) puts the main loop inside `try: ... finally:` so cleanup (`flush_buffer`, `conn.close()`, "thread stopped" log) runs unconditionally.
- `capture/forwarder/preflight.py:15-93` and `capture/session_close/db.py` consistently use `try: ... finally: conn.close()`.

**Status.** ✅ Connection lifecycle is clean across `capture/`, with one filed leak in the watchdog (see Open).

**Open.**
- bugs.md MED-03: `capture/watchdog/db.py:log_restart` leaks the connection if `lookup_compound` raises before the `try:` block. Fix: move `lookup_compound` inside the try.

---

### §1.2 Connection pooling  `n/a`

**Concept.** A connection pool keeps a small set of pre-opened connections ready to hand out to threads/requests. Avoids the TCP + auth + session-setup cost of opening a fresh connection per operation. Standard libraries: `psycopg2.pool.ThreadedConnectionPool`, `pgbouncer` as an external pooler, SQLAlchemy's `QueuePool`. Pools matter most when (a) connection cost is high relative to query cost, or (b) you have many short-lived workers that would otherwise overwhelm `max_connections`.

**In this pipeline.**
- No pool. `grep "psycopg2.pool" capture/ batch/ ingestion/` → 0 hits. Every `psycopg2.connect()` call site (12 of them) opens a fresh connection.
- Workload doesn't justify one today: 4 `StreamThread`s + 1 `ECHOThread` + 1 main-thread preflight + occasional `watchdog` and `session_init/close` ops = at most ~7 simultaneous connections per session, each long-lived (entire session) on the capture side.
- The forwarder + watchdog are also fail-fast — a stale pool connection holding broken transaction state is a class of bug we explicitly don't want to debug.

**Status.** `n/a` Not used by design; documented as a deliberate choice, not an oversight.

**Open.**
- Threshold to revisit: if Phase 4 FastAPI introduces dozens of concurrent HTTP handlers each opening their own connection, that's where a pool earns its keep. Or, if `max_connections` (default 100 in Postgres) becomes a constraint with multi-process deployment, introduce `pgbouncer` at the infra layer rather than `psycopg2.pool` in the app.

---

### §1.3 Transactions & isolation level  ✅

**Concept.** A transaction is a unit of work that's atomic, consistent, isolated, and durable (ACID). "Isolation level" controls what concurrent transactions can see of each other's uncommitted/committed state. Levels (SQL standard): **Read Uncommitted** (rarely used; Postgres treats as Read Committed), **Read Committed** (only see committed data; default in Postgres), **Repeatable Read** (snapshot at transaction start; prevents non-repeatable reads), **Serializable** (full transaction-order serializability; prevents anomalies but increases conflict abort rate). Trade-off: stricter isolation = fewer anomalies but more `SerializationFailure`s to retry. psycopg2's `conn.autocommit = False` means "don't auto-commit after each statement — I'll call `commit()` explicitly."

**In this pipeline.**
- `capture/forwarder/stream_thread/stream_db.py:14` and `capture/echo_handler/db.py:40` both set `conn.autocommit = False`. Every connection is in manual-commit mode.
- No `SET TRANSACTION ISOLATION LEVEL ...` is issued anywhere → all transactions run at Postgres default **READ COMMITTED**.
- Implication: each `cur.execute(...)` followed by `conn.commit()` is one transaction. A failed commit triggers `conn.rollback()` in the exception path (verified pattern in `stream_db.write_rows`, `echo_handler/db.write_row`).
- READ COMMITTED is the right default for this workload — biosignal writes are per-chunk INSERTs that don't compete for the same rows, and per-session reads in batch are scoped to one session_id, so there's no anomaly to worry about. No need to step up to Repeatable Read or Serializable.

**Status.** ✅ Documented as the contract.

**Open.**
- None today. If ARC batch processing ever does a multi-statement read-write transaction that needs a consistent snapshot across statements, that's the moment to consider Repeatable Read explicitly.

---

### §1.4 SQL injection / parameterization  ✅

**Concept.** SQL injection happens when user-controlled input is interpolated into a SQL string instead of bound as a value parameter. The fix: drivers expose a parameterized API (`%s` placeholder in psycopg2, `?` in sqlite3) that binds values *after* the SQL is parsed, so the value can't change the query structure. Identifiers (table/column names) can't be bound as values — they need a separate API (`psycopg2.sql.Identifier` quotes the name safely) or, better, must come from a closed internal mapping never derived from user input.

**In this pipeline.**
- Every site uses `%s` placeholders. `capture/**/sql.py` modules contain SQL templates as plain strings, and every `cur.execute(sql_const, params)` call passes values as the second argument.
- Dynamic table-name interpolation is centralized and hardened. After commit `2dab714`:
  - `batch/arc/processor.py:_query_biosignal_count` uses `sql.SQL("…{table_name}…").format(table_name=sql.Identifier(table_name))`; values still bind via `%s`.
  - `batch/reconciliation/db.py:query_db_counts` + `fetch_existing_sample_indices` use the same `sql.Identifier` pattern.
- Table names in the dynamic SQL come from a closed internal `_STREAM_TABLES` mapping — they cannot be user input. The `sql.Identifier` use is defense-in-depth on top of that.
- Trigger function bodies (in migrations) use PL/pgSQL with `TG_TABLE_NAME` / `TG_OP` — Postgres-side, not application-built SQL strings.

**Status.** ✅ No interpolated values anywhere; identifiers safely quoted.

**Open.**
- None today.

---

### §1.5 Constraints (PK / FK / UNIQUE / CHECK / NOT NULL)  ⚠️

**Concept.** Database constraints are server-enforced invariants on the data — the DB rejects writes that would violate them, regardless of whether the application remembered to check. **PRIMARY KEY**: unique + not null + indexed. **FOREIGN KEY**: row must reference an existing row in another table (or be NULL). **UNIQUE**: prevents duplicate values on a column (or composite). **CHECK**: arbitrary boolean expression evaluated per row (enum-like sets, range guards, JSONB shape checks). **NOT NULL**: column is required. The general principle: enforce as much as you can at the DB level — application checks are racy and skippable; constraint violations are atomic.

**In this pipeline.**

CHECK constraint coverage (broad and consistent):

| Migration | Constraint examples |
|---|---|
| `002_sessions` | `compound_dose_unit` enum |
| `007_respiration_samples` | `breath_phase IN ('inhale', 'exhale', 'hold')` |
| `009_alert_events` | `alert_type`, `severity` enums (alert_type extended in `030`) |
| `010_echo_events` | `event_type`, `source`, `actor_role`, `zone_label`, `confidence_score` enums + range |
| `019_session_signal_metadata` | `modality`, `eeg_channel_count >= 0`, modality-specific enums |
| `027_session_baselines` | `baseline_std >= 0.0`, `sample_count > 0`, `baseline_window_end > baseline_window_start` |
| `028_event_composite_profiles` | `w*_convergence_density >= 0.0`, `jsonb_typeof(...) = 'array'/'object'`, `passed_fdr IS TRUE` |

FK coverage (intentionally lightweight):

| Site | Reference |
|---|---|
| `sessions.compound` | → `compound_reference(compound_id)` |
| `alert_events.compound` | → `compound_reference(compound_id)` |
| `event_composite_profiles.echo_event_id` | → `echo_events(id)` |

Biosignal hypertables don't FK to `sessions` — TimescaleDB hypertable + FK is operationally awkward (FK enforcement across chunks adds write overhead). Per-row `session_id UUID NOT NULL` + the audit/integrity trail are the contract.

UNIQUE gap (the only constraint-coverage weakness):

| Table | Has UNIQUE on natural key? |
|---|---|
| `compound_reference.cas_number` | ✅ |
| `event_composite_profiles (session_id, echo_event_id)` | ✅ |
| `echo_events` | ❌ no UNIQUE on `(session_id, lsl_timestamp, event_type, actor_id, actor_role, zone_label)` — bugs.md LOW-02 |
| `biosignal_integrity_log` | ❌ no UNIQUE on `(session_id, table_name, min_sample_index, max_sample_index)` — re-running reconciliation could write duplicates |
| Biosignal hypertables | PK is the uniqueness contract: `(session_id, lsl_timestamp, channel_id\|device_id, db_insert_time)` |

**Status.** ⚠️ CHECK + NOT NULL coverage is strong. UNIQUE has two real gaps.

**Open.**
- bugs.md LOW-02: add UNIQUE on `echo_events` natural-key composite. Allows concurrent backfill to be safe.
- Add UNIQUE on `biosignal_integrity_log (session_id, table_name, min_sample_index, max_sample_index)` for idempotent reconciliation. Filed in rollup #18.

---

### §1.6 Indexes  ✅

**Concept.** An index is a separate data structure (most commonly a B-tree) the DB maintains alongside a table to speed up lookups by specific columns. Without an index, queries with `WHERE x = ?` do a sequential scan — read every row. With an index, the DB walks the tree in O(log n). Composite indexes index multiple columns in order; the leading column is the "equality column" (must be in the WHERE clause to use the index), trailing columns can be range/sort. Index trade-offs: faster reads + slower writes (every INSERT/UPDATE/DELETE has to update each index) + storage cost.

**In this pipeline.**

`023_indexes.py` (the bulk migration after all core tables exist):

| Table | Indexes |
|---|---|
| `eeg_samples` | `(session_id, lsl_timestamp DESC)`, `(site_id, sponsor_id)`, **`(session_id, channel_id, lsl_timestamp DESC)`** ← EEG-specific |
| `hrv_samples`, `eda_samples`, `respiration_samples` | `(session_id, lsl_timestamp DESC)`, `(site_id, sponsor_id)` |
| `sessions` | sponsor / site / trial_arm / (sponsor_id, site_id) / (site_id, sponsor_id) / status / compound |
| `alert_events`, `echo_events`, `session_feature_vectors`, `session_notes` | session, tenancy, plus alert severity + ECHO time/actor/zone |
| `audit_events` | `(session_id, event_timestamp DESC)` |
| Lower-volume tables | session + tenancy variants |

Later migrations each define their own indexes (they ran after 023, so couldn't be in it):

| Migration | Table | Indexes |
|---|---|---|
| `025` | `clock_drift_log` | session, tenancy |
| `026` | `biosignal_integrity_log` | session |
| `027` | `session_baselines` | session, tenancy, (modality, signal_component) |
| `028` | `event_composite_profiles` | session, echo_event, tenancy, arc_config |

Design choices (from `023_indexes.py:14-55`):
- Composite indexes put the equality column first, the range/sort column second. `(session_id, lsl_timestamp DESC)` serves both `WHERE session_id = ?` and `WHERE session_id = ? ORDER BY lsl_timestamp DESC LIMIT N` in one lookup.
- EEG gets a third composite `(session_id, channel_id, lsl_timestamp DESC)` because per-channel queries dominate.
- Tenancy indexes `(site_id, sponsor_id)` exist on every table for future Phase 4 API queries.

**Status.** ✅ Coverage looks correct for the documented query patterns.

**Open.**
- No `EXPLAIN ANALYZE` spot-check on real session data yet (filed in rollup #19). Will catch surprises like "the planner is picking a tenancy index when the session_time composite would be faster."
- Index bloat is not monitored. With 1-hour chunks + frequent compression this isn't urgent.

---

### §1.7 Migrations & schema chain  ✅

**Concept.** Schema migrations are version-controlled scripts that take the database from one schema state to another. Each migration has an `upgrade()` (forward) and `downgrade()` (reverse). Alembic (the tool this project uses) builds a directed chain via each migration's `revision` + `down_revision` pointers — running `alembic upgrade head` walks the chain and applies each migration in order. The chain must be unbroken (every migration's `down_revision` must point to a real ancestor) and unbranching (no two migrations share a `down_revision` — that would force the DB to apply both branches and Alembic refuses).

**In this pipeline.**

Active chain (`untitledplatform_1a_db/db/alembic/versions/`):

```
001_extensions → 002_sessions → 003_compound_reference → 004_eeg_samples →
005_hrv_samples → 006_eda_samples → 007_respiration_samples → 008_audit_events →
009_alert_events → 010_echo_events → 011_pgvector_columns → 012_compression →
013_compression_policy → 015_schema_version_metadata (skips 014) →
019_session_signal_metadata (skips 016, 017, 018) → 020_audit_triggers →
021_correction_amendment_log → 022_session_environment_log → 023_indexes →
024_watermark_trigger → 025_clock_drift_log → 026_biosignal_integrity_log →
027_session_baselines → 028_event_composite_profiles →
029_echo_events_manual_marker → 030_arc_failure_alert_type
```

Why the numbering gap: migrations 014, 016, 017, 018 live in `optional_governance/` and form a parallel chain rooted at `013_compression_policy` (consent log → electronic signatures → investigational product log → adverse event log). They're for regulated deployments that need 21 CFR Part 11 Subpart C.

Safe because `alembic.ini:7` declares `script_location = untitledplatform_1a_db/db/alembic`. Alembic walks `script_location/versions/` only — `optional_governance/` is not discovered on `upgrade head`.

Up/down symmetry spot-checked:
- `020_audit_triggers.py:115-118` — drops each trigger + the function ✓
- `024_watermark_trigger.py:112-114` — drops trigger then function ✓
- `030_arc_failure_alert_type.py:43-59` — drops new constraint, re-adds prior 6-value CHECK ✓

`SCHEMA.md` accuracy was refreshed in commit `b269df7`. Full SCHEMA ↔ migration cross-check across 001–030 still pending (rollup #11).

**Status.** ✅ Chain unbroken, parallel-tree segregation deliberate, symmetry spot-clean.

**Open.**
- Rollup #11: complete SCHEMA.md sweep.
- Rollup #4: if `optional_governance/` is ever activated, `014_consent_log.down_revision = "013_compression_policy"` collides with `015_schema_version_metadata.down_revision = "013_compression_policy"`. Re-chain 014 from 013 and 015 from 014 at that point.

---

## Tier 2 — Concurrency

### §2.1 Cursor / thread safety  ✅

**Concept.** A driver's documented thread-safety level varies per object. For psycopg2: connections are thread-safe (you can pass one to another thread and use it), but **cursors are not** — a single cursor accessed from two threads can produce lost results, corrupted state, or driver-level segfaults. The safe pattern is "one cursor per thread per operation, created locally and closed promptly" or "create a cursor inside `with` and let the context manager close it." Don't stash a cursor on an instance attribute that multiple threads can reach.

**In this pipeline.**

| Thread | Connection | Cursor pattern |
|---|---|---|
| `StreamThread` (one per modality) | `thread.connect_db()` inside `run()` → fresh `psycopg2.connect()` (`capture/forwarder/stream_thread/stream_db.py:12-15`). | `write_rows`: local `cur = conn.cursor()` → `execute_batch` → `cur.close()` (`stream_db.py:49-52`). `write_integrity_log`: same (`stream_integrity.py:24-45`). `maybe_record_drift`: `with conn.cursor() as cur:` (`stream_drift.py:39-54`). |
| `ECHOThread` | `thread.connect_db()` → fresh `psycopg2.connect()` (`capture/echo_handler/db.py:35-50`). | `db.write_row`: `with conn.cursor() as cur:` (`echo_handler/db.py:70-71`). |
| Forwarder main thread | Holds no DB connection during capture. | n/a |
| `preflight` (pre-thread) | Local connection in `with` blocks (`capture/forwarder/preflight.py:15-93`). | `with conn.cursor() as cur:` throughout. |
| `session_init`, `session_close`, `watchdog` | Sequential main-thread code. | Local cursor per op. |

Cross-checks:
- `Grep "self._cur | thread._cur | self._conn | thread._conn"` across `capture/` → **0 matches**. Connections/cursors are never stashed on instance state.
- `Grep "psycopg2.connect | psycopg2.pool"` → 12 call sites, every one owns its lifecycle locally. No shared pool.

**Status.** ✅ No cross-thread cursor sharing anywhere in `capture/`.

**Open.**
- Intra-thread cursor leak noted in §2.4.

---

### §2.2 Threading model in this pipeline  ✅

**Concept.** A "threading model" is the shape of how a process splits work across threads, what state is shared, and how that shared state is protected. Failure modes: race conditions (two threads reading-modifying-writing the same variable), deadlocks (two threads each holding a lock the other needs), starvation (a thread can never make progress), torn writes (a non-atomic write interrupted halfway). Tools for protection: `Lock` (mutual exclusion), `RLock` (reentrant), `Event` (broadcast signal), `Queue` (thread-safe FIFO), `Condition` (lock + wait/notify). Python's GIL prevents true parallel bytecode execution but releases around C-level I/O — so I/O-bound parallelism does happen.

**In this pipeline.**

| Process | Threads spawned | Shared sync primitives |
|---|---|---|
| `capture.lsl_forwarder` | 4 × `StreamThread` (EEG, HRV, EDA, Respiration) + 1 × `ECHOThread` | `stop_event` (`threading.Event`), `XDFWriter` (instance, owns its own `threading.Lock`) |
| `capture.watchdog` | 0 — uses `subprocess.Popen` to manage the forwarder process | cross-process (signals + DB) |
| `capture.synthetic_board` | one thread per modality outlet | local `stop_event`; no DB |
| `capture.marker_simulator` | main thread + `threading.Event` | no DB |
| `session_init`, `session_close` (CLI) | main thread only | n/a |

Shared mutable state — and how it's protected:

| State | Type | Protection | Risk |
|---|---|---|---|
| `XDFWriter._f` (open file, shared across all 5 worker threads) | `IO[bytes]` + `threading.Lock` | `self._lock` held around every `write_*` and `close()` (`capture/xdf/writer.py:60`) | Was high without lock; safe today. |
| `stop_event` | `threading.Event` | Internally locked (CPython uses a `Condition`). Atomic `set`/`is_set`. | Safe. |
| `thread.buffer` (per-thread) | `collections.deque(maxlen=200)` | Each thread owns its own buffer. | Safe by ownership. |
| `thread._sample_index`, `_chunk_count`, `_last_drift_time` | int/float on thread instance | Each thread reads/writes only its own attributes. | Safe by ownership. |
| DB connection per thread | `psycopg2.connection` | Each thread opens its own. Never passed across threads. | Safe by ownership. See §2.1. |
| `logging.Logger` (shared across all stream threads) | `logging.Logger` | Python `logging` is thread-safe by design. | Safe. |

Signal handlers:
- `capture/forwarder/runtime.py:45-47` installs SIGTERM (and SIGBREAK on Windows) handlers that call `stop.set()`. Python delivers signals to the main thread only, so the handler runs there. `stop_event.set()` is atomic — no race with worker threads polling `.is_set()`.
- Watchdog's SIGTERM handler sets a flag, but `time.sleep(delay)` between restarts is not signal-interruptible (bugs.md LOW-03). Cosmetic — next loop iteration checks the flag.

Cross-thread ordering invariants:
- **XDF before DB:** every `StreamThread` writes the XDF chunk before the DB row (`capture/forwarder/stream_thread/stream_chunks.py`). XDF is the reconciliation source of truth, so it must lead.
- **stop_event propagation:** commit `b4d3111` made `run_stream_thread` set `stop_event` on RuntimeError so sibling threads wind down cleanly. Without this, one thread dying silently could leave the rest running.

Why the GIL doesn't bite here: the threads spend most time in C-level I/O (LSL `pull_chunk`, psycopg2 `execute_batch`, file `write`) where the GIL is released. So real parallelism happens — the synchronization above isn't theoretical.

**Status.** ✅ Clean ownership model, single shared mutable resource (`XDFWriter`) protected by a lock.

**Open.**
- bugs.md MED-08: `flush_buffer` has no time budget on shutdown — could exceed watchdog `GRACEFUL_SHUTDOWN_TIMEOUT_S` and get SIGKILLed mid-flush.
- bugs.md LOW-03: watchdog `time.sleep(delay)` not SIGTERM-interruptible.

---

### §2.3 Deadlock + serialization retry  ⚠️

**Concept.** A deadlock occurs when two transactions form a wait cycle (T1 holds lock A and wants lock B; T2 holds B and wants A). Postgres detects deadlocks (default `deadlock_timeout = 1s`), aborts one transaction with `DeadlockDetected`, and lets the other proceed. A `SerializationFailure` is the analogous abort under higher isolation levels when the planner can't serialize the transactions. **Both errors are transient — the standard pattern is to retry** with a brief backoff. The application code that surrounds the SQL needs to distinguish "transient — retry the transaction" from "fatal — drop and report" (e.g., constraint violation, type error, syntax error).

**In this pipeline.**

| Error class | Treatment | Site |
|---|---|---|
| `psycopg2.OperationalError` (connection dropped, server gone) | Buffer the chunk into `thread.buffer` for retry on next reconnect | `stream_db.py:54-61`, `echo_handler/db.py:90-96` |
| `psycopg2.Error` (catch-all, includes deadlock + serialization failures) | Rollback + log + drop the chunk silently | `stream_db.py:62-68`, `echo_handler/db.py:97-111` |

The current `except psycopg2.Error` catch-all treats deadlock and serialization failures as permanent drops. That's wrong for the transient classes — a chunk lost to a transient deadlock will be re-discoverable via XDF reconciliation at session close, but the failure is silent at runtime.

**Status.** ⚠️ Transient retry path missing for the right subset of `psycopg2.errors`.

**Open.**
- bugs.md MED-07 (biosignal) + LOW-04 (ECHO): catch `psycopg2.errors.DeadlockDetected` and `psycopg2.errors.SerializationFailure` explicitly and append to `thread.buffer` for retry. Only truly fatal errors (`DataError`, `IntegrityError`) should drop the chunk, and those should log at ERROR with the row payload.

---

### §2.4 Cursor leak on exception  ⚠️

**Concept.** When a cursor is created with `cur = conn.cursor()` and not closed via a context manager, the only paths that close it are explicit `cur.close()` calls or garbage collection. If the SQL raises between `cursor()` and `close()`, the cursor stays open until GC reclaims the underlying object — a soft leak. The connection itself is still usable (the cursor is a server-side resource, but a small one), so this is hygiene, not a correctness bug. The fix is universal: use `with conn.cursor() as cur:` — Python's context-manager protocol closes the cursor on exit, exception or not.

**In this pipeline.**

- `capture/forwarder/stream_thread/stream_db.py:49-52` — raw `cur = conn.cursor()` / `execute_batch` / `cur.close()` after `conn.commit()`. If `execute_batch` raises, `cur` leaks until GC.
- `capture/forwarder/stream_thread/stream_integrity.py:24-45` — same pattern.
- `capture/forwarder/preflight.py`, `capture/echo_handler/db.py`, `capture/session_close/db.py` — all use `with conn.cursor() as cur:` throughout. Clean.

**Status.** ⚠️ Two known sites with raw-cursor pattern. Low priority but trivial fix.

**Open.**
- Rollup #10: convert the two sites to `with conn.cursor() as cur:` (~3 lines each).

---

## Tier 3 — Domain integrity (the clinical-grade audit story)

### §3.1 Audit trail (triggers-only writes)  ✅

**Concept.** An "audit trail" is a tamper-evident record of every change to data: who/what wrote what and when. In a regulated context (21 CFR Part 11) the audit trail must be immutable from the application side — that is, application code must not be able to forge an audit row or skip one. The standard pattern: implement the audit at the DB level via triggers, and revoke the application role's INSERT/UPDATE/DELETE on the audit table. The audit is then a side-effect of every legitimate write, not something application code remembers to call.

**In this pipeline.**

- Trigger function `audit_trigger_full_func()` in migration `020_audit_triggers.py:73-103`. Attached to: `sessions`, `alert_events`, `echo_events`, `session_feature_vectors`, `session_notes`, `schema_version_log`, `session_signal_metadata`.
- Function uses PL/pgSQL `IF/ELSE` on `TG_TABLE_NAME` (because SQL `CASE` would eagerly evaluate `NEW.session_id` even on the `sessions` table which has no such column — design choice noted in the migration `:67-72`).
- Biosignal hypertables (eeg/hrv/eda/respiration) are intentionally excluded — they'd generate millions of audit rows per session. They use `biosignal_integrity_log` (migration 026) for chunk-level provenance instead — see §3.3.
- Verification: `grep -rn "INSERT INTO audit_events" capture/ batch/ ingestion/ storage/ src/` should produce **0** matches (audit insertion is migration-only).

**Status.** ✅ Verified.

**Open.**
- None today. Rollup #12: `audit_trigger_smart_func` must match the live DB version (deployment-side check, CLAUDE.md known issue #3).
- Rollup #13: `row_to_json` PII exclusion must be added if any real-PII column ever lands on a trigger-watched table (CLAUDE.md known issue #4).

---

### §3.2 Watermark gating  ⚠️

**Concept.** A "watermark" is a marker event written to an event log when some upstream contract is satisfied. Downstream consumers wait on the watermark before they start work, so they never process incomplete data. In this codebase the contract is: "the session is fully captured, reconciled, and durable, so batch processing may begin." Without a watermark, you'd get a race where batch jobs read a session mid-flush and produce wrong answers.

**In this pipeline.**

- Trigger function `sessions_watermark_func()` in migration `024_watermark_trigger.py:25-102`. Fires `AFTER UPDATE ON sessions FOR EACH ROW` only on a real status transition (`NEW.status != OLD.status`).

| Status transition | Events written to `audit_events` |
|---|---|
| → `'closed'` | `'session_status_transition'` + `'watermark_verified'` |
| → `'failed'` | `'session_status_transition'` + `'watermark_failed'` |
| any other | `'session_status_transition'` only |

- Batch entrypoints check for `watermark_verified` in `audit_events` before they fire.
- Session_close writes the terminal status via `capture/session_close/workflow.py` → `close_session` in `batch/reconciliation/db.py:79`. That UPDATE triggers the watermark function.

**Status.** ⚠️ Mechanism is correct. Two known holes:

1. CLAUDE.md known issue #2 (rollup #1): aborted sessions (dose administered, session aborted) are clinically significant under ITT analysis but never reach `'closed'` or `'failed'` today. Phase 5b will add an `aborted` state with its own watermark path.
2. bugs.md MED-04 (rollup #2): `capture/session_close/workflow.py` can leave a session in `'closing'` if `reconcile_session` raises — no terminal status, no watermark fires, batch is permanently blocked for that session. Fix: wrap reconciliation in try/except and explicitly set status to `'failed'` on unexpected error.

**Open.**
- Rollup #1 (aborted sessions, deferred).
- Rollup #2 (stuck-in-'closing', filed).

---

### §3.3 Tamper-evidence (chunk hashes)  ⚠️

**Concept.** Tamper-evidence means: if a row in the data was modified after-the-fact, you can prove it. The standard mechanism is to store a hash of the data alongside the data; at audit time, recompute the hash and compare. For high-volume data where a per-row hash is too expensive, you can hash a chunk and store one hash per chunk. The key property: the hash record must be atomically linked to the data it covers — if the data exists without the hash record (or vice versa), tamper-evidence has a hole at exactly the boundary you care about.

**In this pipeline.**

- `biosignal_integrity_log` table (migration 026) stores one row per chunk with `chunk_hash`, `min_sample_index`, `max_sample_index`, `row_count`, `hash_method = 'md5'`.
- Hash computed by `capture/forwarder/stream_thread/stream_integrity.py:18-22` — MD5 over JSON-sorted chunk fields. Marked `usedforsecurity=False` because MD5 here is used for completeness/replay, not as a security primitive.
- Sort keys + hash fields are per-modality (`thread._hash_fields`, `thread._hash_sort_keys`, set per-stream in `streams.py`).
- Reconciliation + backfill use the integrity log to detect gaps.

**Status.** ⚠️ Mechanism is correct but has two structural gaps:

1. **Separate transactions (bugs.md MED-06).** `stream_db.write_rows` commits the sample INSERT at `stream_db.py:51`, then `stream_integrity.write_integrity_log` runs and commits the integrity row in a *separate* transaction at `stream_integrity.py:44`. If the integrity INSERT fails (deadlock, transient error), the samples are durable but no chunk_hash exists. Tamper-evidence has a hole exactly where it's most likely to be exploited.

2. **Buffer-flush path (bugs.md MED-05).** `stream_chunks.write_rows_and_integrity` calls `flush_buffer(conn)` first to drain older buffered chunks, then writes the *current* chunk + integrity row. Buffered chunks that get re-written via `flush_buffer` have **no `biosignal_integrity_log` row** ever written for them — the chunk-hash record is missing for any chunk that survived a DB drop. Reconciliation at session_close compares DB row count vs XDF row count and likely matches, but the chunk-level integrity audit will have holes corresponding exactly to the DB-unavailability window.

Recommended fix (both gaps): combine the sample-write + integrity-write into one transaction; teach `flush_buffer` to call `write_integrity_log` after each successful chunk write.

**Open.**
- Rollup #5 (MED-06): integrity log in separate transaction.
- Rollup #6 (MED-05): integrity log skipped on buffer-flush path.

---

### §3.4 XDF ↔ DB reconciliation parity  ✅

**Concept.** Parity = "two storage layers should hold the same data; if they diverge, you can reconcile." In streaming pipelines this typically means writing to both a durable log (or backup) and a queryable store, with the durable log as the source of truth on disagreement. Reconciliation is the process of comparing the two and backfilling the queryable store from the durable log when it lags or drops.

**In this pipeline.**

- The forwarder writes XDF **first**, then DB (parallel write pattern in `capture/forwarder/stream_thread/stream_chunks.py`). XDF is the reconciliation source of truth.
- `XDFWriter` (`capture/xdf/writer.py:60`) has its own `threading.Lock` — concurrent writes from all 5 worker threads serialize at the file level, no torn writes.
- At session close, `capture/session_close/reconciliation.py` → `batch/reconcile.py` calls `batch/reconciliation/db.py:query_db_counts` + `batch/reconciliation/xdf.py:read_xdf_counts`, computes the gap per stream, and runs `batch/reconciliation/backfill.py:run_backfill` to fill any gap from XDF.
- ECHO events follow the same pattern (XDF marker stream → `echo_events` table).

**Status.** ✅ Two-write ordering correct; reconciliation + backfill wired end-to-end.

**Open.**
- bugs.md MED-09 (rollup #7): XDF write failures are logged but never escalate to the watchdog or operator. If XDF writes fail repeatedly mid-session, reconciliation reports a non-zero gap but has no ground truth to backfill from.

---

### §3.5 Tenancy enforcement (`sponsor_id` / `site_id`)  ⚠️

**Concept.** Multi-tenant data means rows belonging to different customers/sites/sponsors live in the same table. The tenancy contract is: **every query that touches user-scoped data filters by tenant**, and writes carry the tenant ID on every row. The enforcement is application-side (every query has the WHERE clause), schema-side (every row has the column NOT NULL), and ideally also DB-side via row-level security (RLS) or a separate role per tenant. Missing the filter on a single query is enough to leak across tenants.

**In this pipeline.**

Coverage in `capture/`:

| Site | Status |
|---|---|
| `capture/watchdog/db.py:21, 105, 130` | ✅ all three SELECT/UPDATE filter `AND sponsor_id = %s` |
| `capture/forwarder/preflight.py:19, 43, 68` | ✅ all three filter |
| `capture/session_close/db.py:32, 50, 70` | ✅ all three filter |
| `capture/session_init/sql.py`, `workflow.py` | ✅ INSERTs include `sponsor_id` on every row; reads filter |
| `capture/echo_handler/db.py:write_row` | ✅ row carries `sponsor_id`; write-only |

Coverage in `batch/`:

| Site | Status |
|---|---|
| `batch/reconciliation/db.py:fetch_session_meta` (line 125) | ❌ `WHERE id = %s` only — no sponsor_id filter (bugs.md LOW-01) |
| `batch/reconciliation/db.py:close_session` (line 79) | ⚠️ Inherits LOW-01 via `fetch_session_meta` |
| `query_db_counts`, `fetch_existing_sample_indices` | n/a — counts/reads scoped to a session UUID for reconciliation, not per-row patient reads |

Row-level security (RLS): not used. Phase 4 work.

**Status.** ⚠️ One filed gap in `batch/`.

**Open.**
- Rollup #3 (LOW-01): add sponsor_id parameter + WHERE clause to `fetch_session_meta` and propagate through `close_session`. ~5 lines.

---

### §3.6 Pseudonymous IDs  ✅

**Concept.** A pseudonymous ID is a token (typically a UUID) that uniquely identifies a subject but is not derivable from their real identity. The mapping from token → identity lives outside the system that holds the data — e.g., in a separate enrollment registry only the coordinator can access. The data tables themselves never contain a real name, email, DOB, or other PII. This is the standard 21 CFR Part 11-compatible identity model.

**In this pipeline.**

- Schema enforcement: `participant_id UUID NOT NULL` on every table that carries it (sessions, eeg_samples, hrv_samples, eda_samples, respiration_samples, echo_events, alert_events, session_signal_metadata, clock_drift_log, biosignal_integrity_log, session_baselines, event_composite_profiles, session_feature_vectors). The DB rejects non-UUID values.
- Logger enforcement (post `2dab714`): `capture/logger.py:_FORBIDDEN_LOG_KEYS = {address, api_key, date_of_birth, dob, email, name, participant_name, password, phone, secret, ssn, token}`. The JSON formatter drops these keys from `extra=` payloads at serialization time, even if a caller accidentally passes one.
- XDF enforcement (post `2dab714`): every user-controlled value written to the XDF stream-header XML is passed through `html.escape()` (`capture/xdf/metadata.py`) to prevent XML injection if a tokenized ID ever contains `<`, `>`, or `&`.

**Status.** ✅ Schema + logger + XDF all enforce.

**Open.**
- Rollup #13 (CLAUDE.md known issue #4): `row_to_json(NEW)::jsonb` in the audit trigger copies the entire row. Safe today because all current columns are pseudonymous. If a real-PII column is ever added to a trigger-watched table, the trigger needs JSONB `-` exclusion before that migration runs.

---

### §3.7 Two-timestamp invariant (`lsl_timestamp` vs `db_insert_time`)  ✅

**Concept.** When recording sensor data, there are at least two timestamps that matter: the **device time** (when the sample was actually captured) and the **system time** (when it arrived in the database). They're never the same — network latency, buffering, and processing time create a gap. Collapsing them into one column is a regulatory failure: you can no longer prove what was recorded vs. when it was stored. The invariant is: keep both as separate columns, NOT NULL, never derive one from the other.

**In this pipeline.**

- Every biosignal row carries both: `lsl_timestamp DOUBLE PRECISION NOT NULL` (epoch seconds from `pylsl.local_clock()`) and `db_insert_time TIMESTAMPTZ NOT NULL DEFAULT NOW()` (timezone-aware wall clock from Postgres).
- Row builders never derive one from the other. `capture/forwarder/rows.py` populates `lsl_timestamp` from LSL directly and lets `db_insert_time` default to `NOW()` server-side.
- The hypertable PK is `(session_id, lsl_timestamp, channel_id, db_insert_time)` — both timestamps participate, both must be present, and TimescaleDB requires the partitioning column (`db_insert_time`) in the PK.
- Audit trigger function `audit_trigger_full_func()` records `event_timestamp = NOW()`; it never overwrites `lsl_timestamp` with `event_timestamp`.
- `lsl_timestamp` being `DOUBLE PRECISION` (not `TIMESTAMPTZ`) is intentional — it's a *clock offset*, not a wall-clock time. LSL provides it from a monotonic clock, and Postgres TIMESTAMPTZ would lose precision and tie it to a calendar that doesn't apply.

**Status.** ✅ Schema + app + trigger all uphold the invariant.

**Open.**
- None today. Re-verify if any new datetime column is added to a biosignal or event table.

---

### §3.8 Timezone consistency  ✅

**Concept.** A "timezone-aware" timestamp (Postgres `TIMESTAMPTZ`, Python `datetime` with `tzinfo`) carries a UTC offset so absolute time is unambiguous. A "naive" timestamp (Postgres `TIMESTAMP`, Python `datetime` with `tzinfo=None`) does not — the value's meaning depends on the system clock's local zone, which differs across deployments. Mixing them is a recipe for bugs: a write from a `UTC+0` machine read by a `UTC-7` machine silently shifts by 7 hours. The rule: pick aware everywhere.

**In this pipeline.**

- **Schema:** every persisted datetime column is `TIMESTAMPTZ NOT NULL DEFAULT NOW()`. Verified by `grep "TIMESTAMP\b\|TIMESTAMPTZ\b" untitledplatform_1a_db/db/alembic/versions/` — zero hits for bare `TIMESTAMP`. Covered tables: sessions, eeg/hrv/eda/respiration samples, audit_events, alert_events, echo_events, session_feature_vectors, session_notes, schema_version_log, session_signal_metadata, data_correction_amendment_log, session_environment_log, clock_drift_log, biosignal_integrity_log, session_baselines, event_composite_profiles.
- **Application:** `grep "datetime.now()\|datetime.utcnow()\|datetime(" capture/` → zero hits for naive `datetime` constructions. Only two `time.time()` calls (in `capture/xdf/samples.py:13, 30`) which write POSIX seconds-since-epoch into the binary XDF chunk header — that's the correct value for that field, not a naive-datetime hazard.
- **DB-side `NOW()`** returns `TIMESTAMPTZ`, so `db_insert_time DEFAULT NOW()` columns always carry the server's TZ.

**Status.** ✅ Schema + app + DB function results all timezone-aware.

**Open.**
- None. Re-verify if any new datetime column or app-side timestamp is added.

---

## Tier 4 — TimescaleDB specifics

### §4.1 Hypertable chunk sizing  ✅

**Concept.** A TimescaleDB hypertable looks like a regular table to your application but is auto-partitioned by a time column into "chunks" — separate child tables under the hood. The `chunk_time_interval` determines how much wall-clock time each chunk covers. Smaller chunks = more chunks (chunk metadata overhead grows; planner has more to consider). Larger chunks = each chunk holds more data (per-chunk maintenance like compression and reindexing takes longer). The TimescaleDB documentation recommends sizing chunks so the most recent uncompressed chunk + indexes fits in RAM (often quoted as ~25% of RAM as a rough rule of thumb).

**In this pipeline.**

All 4 biosignal hypertables use `chunk_time_interval = INTERVAL '1 hour'` partitioned on `db_insert_time`:

| Table | Expected rows per 1-hour chunk |
|---|---|
| `eeg_samples` | 250 Hz × 8 channels × 3600 s = **7.2 M rows** |
| `hrv_samples` | ~1 Hz × 3600 s = **3,600 rows** |
| `eda_samples` | 4 Hz × 3600 s = **14,400 rows** |
| `respiration_samples` | 4 Hz × 3600 s = **14,400 rows** |

Why `db_insert_time` and not `lsl_timestamp` for partitioning: TimescaleDB needs a true `TIMESTAMPTZ` column on the partition. `lsl_timestamp` is `DOUBLE PRECISION` (intentionally, see §3.7). The PK still includes `lsl_timestamp` for natural-key uniqueness — `db_insert_time` is appended to the PK because TimescaleDB requires the partitioning column in every unique constraint. See `004_eeg_samples.py:47-58`.

Why 1 hour:
- 4-hour session → 4 chunks per table. 8-hour ibogaine → 8 chunks. 30-minute test → one mostly-empty chunk (TimescaleDB doesn't pre-allocate disk for empty chunks).
- 7.2 M EEG rows per chunk is large but well within Postgres+TimescaleDB's comfortable range. Compression (§4.2) shrinks stored size by ~80% once a chunk passes age.

**Status.** ✅ Sizing reasonable for current session durations.

**Open.**
- If a session ever crosses 8+ hours regularly, revisit chunk size — 12 h sessions are rare but possible for ibogaine. Not urgent.

---

### §4.2 Compression policy  ✅

**Concept.** TimescaleDB columnar compression stores chunk data column-by-column instead of row-by-row, with extra encoding (delta + run-length + dictionary) that exploits the repetitive nature of time-series data. Compression ratios of 80–95% are typical. Trade-off: a compressed chunk is *not* writable until you decompress it. So the policy is "compress chunks older than X" where X must be larger than the longest plausible window during which data might still be backfilled.

**In this pipeline.**

- Migration `012_compression.py` sets compression settings per table:
  - EEG: `segmentby = (session_id, channel_id)`, `orderby = (lsl_timestamp DESC)`
  - HRV / EDA / Respiration: `segmentby = (session_id, device_id)`, `orderby = (lsl_timestamp DESC)`
- Migration `013_compression_policy.py` adds the auto-compression policy: `add_compression_policy(table, compress_after => INTERVAL '1 day')` on all 4 hypertables.
- The 1-day buffer means: during a session, data stays uncompressed and fully writable; within 24 hours after session close, the chunks are compressed automatically. No manual intervention.
- `segmentby` exists so per-channel queries stay fast on compressed data (rows with the same `(session_id, channel_id)` are stored together inside a compressed chunk).
- `orderby = (lsl_timestamp DESC)` means "last N minutes" reads only the front of each compressed segment.

**Status.** ✅ Policy correct for the documented session window.

**Open.**
- Rollup #14 (CLAUDE.md known issue #5): document the `decompress_chunk → backfill → compress_chunk` procedure for cases where a backfill needs to cross the 1-day boundary. Operational doc.

---

### §4.3 Continuous aggregates (not used yet)  📝

**Concept.** A TimescaleDB "continuous aggregate" is a materialized view that's updated incrementally as new chunks close — you get the speed of a pre-computed aggregate without manually re-running the query. Useful when downstream consumers always want a coarser time granularity than the raw data (e.g., 1-second HRV when raw is 4 Hz EDA + 1 Hz HRV, or per-minute averages over per-sample data). Trade-off: storage + maintenance overhead.

**In this pipeline.**

- Not used. No continuous aggregates are defined in any migration.
- ARC batch (`batch/arc/processor.py`) reads raw rows for its windowing logic. Per-minute HRV / EDA / respiration aggregates *could* be a continuous aggregate to back ARC's window queries instead of scanning raw rows each time, but the current data scale (3,600 HRV rows per session-hour) doesn't justify the maintenance complexity.

**Status.** 📝 Deliberate non-use. Documented so future-you knows it's available.

**Open.**
- Revisit when ARC batch query latency becomes a measurable bottleneck. Likely Phase 5b territory.

---

### §4.4 Retention policy (deferred)  📝

**Concept.** A TimescaleDB "retention policy" drops or rolls up chunks older than a configured age automatically. Used when storage cost or regulatory deletion mandates require old data to leave. Without a policy, chunks accumulate forever.

**In this pipeline.**

- No retention policy is set. Old session chunks live forever once compressed.
- Acceptable for a local-research MVP: data is the product, dropping it would defeat the purpose. In a regulated multi-trial deployment, retention would be policy-driven (e.g., "raw biosignals retained for trial duration + 25 years per 21 CFR Part 11 §11.10(c)").

**Status.** 📝 Deferred. MVP scope.

**Open.**
- Rollup #20: revisit retention when deployment target requires it.

---

## Tier 5 — Operational / deployment

### §5.1 DB role / privilege architecture  ❌

**Concept.** Postgres roles are the unit of access control — users, groups, and login accounts are all "roles" with different privilege sets. The "principle of least privilege" says: every process gets the minimum permissions needed to do its job. For an audit table to be tamper-evident, the application role must not have UPDATE or DELETE on it — only INSERT (and even that only via triggers from other tables). Superuser access exists, but it's vaulted, used only for migrations and break-glass operations, and its use is itself audited.

**In this pipeline.**

- Today: a single superuser role is used everywhere. The `DATABASE_URL` in `.env.example` connects as a single user (`untitled`) that has full permissions including DROP on audit tables.
- `audit_events` is "append-only" in the sense that application code doesn't write to it (only triggers do — see §3.1). But there's no DB-side enforcement preventing the application user from issuing `DELETE FROM audit_events`. A buggy script or malicious actor with the credentials could erase the audit trail.
- The proposed Phase 4 role layout (from CLAUDE.md "Working roles required before UCSF"):
  - `app_role`: INSERT only on audit tables, INSERT/UPDATE on session + event tables, no DELETE anywhere.
  - `coordinator_role`: INSERT on session and event tables; no access to `system_users` or `data_access_log`.
  - `readonly_role`: SELECT-only for reporting and dashboards.
  - Superuser credentials vaulted; never used in production code paths.

**Status.** ❌ Single superuser today. CLAUDE.md known issue #1 — required before any real UCSF session.

**Open.**
- Implement Phase 4 role layout: write the migration that creates the roles + grants, update `.env.example` to show the new `DATABASE_URL` per role, document the deployment workflow.
- Rollup item promoted to its own section here.

---

### §5.2 TLS in transit  ⚠️

**Concept.** A psycopg2 / libpq connection can run over TLS (encrypted) or plain TCP. The `sslmode=` parameter in the DSN controls behavior: `disable` (never use SSL), `allow` (try non-SSL first, fall back to SSL), `prefer` (default; try SSL first, fall back to non-SSL), `require` (must use SSL but don't verify the cert), `verify-ca` (cert must chain to a trusted CA), `verify-full` (cert must chain AND match the hostname). For any non-localhost target, `require` is the minimum; `verify-full` is the production move.

**In this pipeline.**

- `config/settings.py:120` reads `DATABASE_URL = _get("DATABASE_URL", "")` from `.env`. The example value in `.env.example:13` is `postgresql://untitled@localhost:5435/untitledplatform_1a` — **no `sslmode=` parameter**.
- Without `sslmode=`, libpq uses its default of `prefer`: try SSL, fall back to non-SSL if the server doesn't offer it. For localhost Docker this is fine; the connection never leaves the loopback.
- For any deployment where the Postgres host is on a separate machine or in a separate network, the `DATABASE_URL` must explicitly set `sslmode=require` (or stricter). The deployment-time configuration owns this — code change isn't needed today, but `.env.example` should grow a commented note about it.

**Status.** ⚠️ Localhost-safe today, deployment-incomplete.

**Open.**
- Update `.env.example` with a commented production example: `# DATABASE_URL=postgresql://user:pass@db.host/db?sslmode=verify-full`.
- When the production target exists, document the cert provisioning + rotation procedure.

---

### §5.3 Secrets management for `DATABASE_URL`  ✅

**Concept.** A secret (DB password, API key, signing key) must not appear in source control, must be loadable by the application at runtime, and must be rotatable without code changes. Standard patterns: environment variables loaded from a `.env` file at startup; secrets store / vault that the app reads at boot; sealed/encrypted env files. The `.env` pattern is the simplest and works for single-host deployments; vaulted secrets are the standard for multi-host.

**In this pipeline.**

- `.env` lives at the repo root, loaded by `config/settings.py:19` via `python-dotenv`'s `load_dotenv(...)`.
- `config/settings.py:_require(key)` raises `RuntimeError` immediately on import if a required env var is missing — fail-loud pattern. Verified at `settings.py:22-29`.
- `.gitignore` includes `.env` so it's never committed.
- `.pre-commit-config.yaml` has a `no-env-files` hook that blocks any `.env` file commit at the hook level (defense in depth).
- `.env.example` is committed and lives next to `.env`, showing the variable names + safe placeholder values (e.g., `DB_PASSWORD=CHANGE_ME`).
- No rotation story today — rotating the DB password means stopping all processes, updating `.env`, restarting. Acceptable for a single-host research-lab MVP.

**Status.** ✅ Chain covered for MVP scope.

**Open.**
- For a multi-host deployment: introduce a vault (e.g., AWS Secrets Manager, HashiCorp Vault) and a `config/settings.py` fetch path that prefers vault → env var → fail. Phase 4+ work.
- Document the rotation procedure for the MVP path: stop processes → edit `.env` → restart → verify connection.

---

### §5.4 Backup / disaster recovery  ⚠️

**Concept.** "Backup" = a copy of data that can restore the system after data loss. "DR" = the procedure to actually do the restore, tested. Variants: **logical backup** (`pg_dump`, restore-via-SQL — slow but portable); **physical backup** (filesystem-level snapshots, WAL archiving, PITR — fast but tied to the exact Postgres version); **application-level backup** (the app writes its own backup of the data it owns; in time-series systems this is sometimes more useful than a DB dump). The DR procedure must specify: backup schedule, retention, restore procedure, RTO (recovery time objective) and RPO (recovery point objective — how much data are you OK to lose).

**In this pipeline.**

- **Application-level backup:** XDF files are written in parallel with DB inserts during every session (`capture/xdf/writer.py`). One XDF file per session under `data/xdf_backups/`. This covers all biosignal samples + ECHO markers durably on the filesystem, independent of the DB.
- **What XDF backup does NOT cover:** `audit_events`, `sessions`, `session_signal_metadata`, `clock_drift_log`, `biosignal_integrity_log`, `alert_events`, ARC-related tables (`session_baselines`, `event_composite_profiles`). If the DB dies between sessions, these are gone unless `pg_dump` was run.
- **No `pg_dump` automation, no WAL archiving, no PITR setup** in the current MVP. A DB-level catastrophe (disk loss, table drop) requires manual restore from whatever snapshot exists.
- **pg_dump compatibility with compressed TimescaleDB chunks:** TimescaleDB 2.x supports it via the `--no-tablespaces` and the `timescaledb-backup` extension. Worth verifying once before relying on it.

**Status.** ⚠️ Per-session XDF covers biosignals only. DB-level backup not configured.

**Open.**
- Add a cron / systemd-timer that runs `pg_dump` nightly to a separate filesystem.
- Document the restore procedure for both scenarios: (a) DB lost, biosignal sessions recoverable via XDF backfill; (b) DB lost AND session-level metadata (sessions, audit) lost — what's the RPO?
- Test the restore procedure end-to-end at least once before any real UCSF session.

---

### §5.5 Disk capacity / data growth  ⚠️

**Concept.** Time-series workloads grow continuously. The disk grows monotonically until you compress, drop, or archive. Capacity planning means: (a) estimate per-unit-of-time growth at the data's source rates, (b) budget storage based on retention + compression assumptions, (c) monitor actual growth and alert before disk fills.

**In this pipeline.**

- Per-session growth (from migration `012_compression.py:7-19`):

| Modality | Raw size per 4-hour session |
|---|---|
| EEG (256 Hz × 8 ch) | ~2.3 GB |
| HRV (~1 Hz) | <1 MB |
| EDA (16 Hz) | ~15 MB |
| Respiration (~1 Hz) | <1 MB |

- After TimescaleDB columnar compression (chunks ≥ 1 day old): typically 10–20% of original. Estimated compressed footprint per 4-hour session: **~250–600 MB** total.
- Plus the XDF backup written in parallel: full-fidelity binary biosignal stream + markers, roughly equivalent uncompressed (~2.5–3 GB per 4-hour session).
- No monitoring today. No alert when free disk drops below a threshold. No automated cleanup.

**Status.** ⚠️ Per-session budget known; observability missing.

**Open.**
- Add a periodic check (cron / systemd-timer / Grafana panel via the docker-compose'd Grafana) that reports `pg_database_size('untitledplatform_1a')` and `df -h /var/lib/docker/volumes/...` and alerts on threshold.
- Document the per-session budget so future-you can compare actuals: "expect <1 GB DB growth per 4-h session after compression; XDF adds another ~3 GB."

---

### §5.6 Failure recovery procedures  ⚠️

**Concept.** "Failure recovery" is the documented set of procedures for what to do when a specific failure mode occurs. The failure modes typically split into: **process failure** (the application died but the data + DB are fine), **DB failure** (Postgres crashed, possibly with data loss in the last second or two), **disk failure** (data loss in whatever wasn't backed up), and **network failure** (transient connectivity loss). Each has a different recovery procedure, and each procedure should be documented and tested before production.

**In this pipeline.**

| Failure | Current recovery |
|---|---|
| **Forwarder process crash** | Watchdog (`capture.watchdog`) detects exit, restarts up to `MAX_RESTARTS=5` times with backoff. Buffered chunks in the dying thread are lost; new process resumes from current LSL inlet position. XDF holds the truth, and reconciliation at session close fills any gap from XDF. |
| **DB connection drop mid-session** | `OperationalError` in `stream_db.write_rows` buffers chunks into `thread.buffer` (deque, maxlen 200). Reconnect via `try_reconnect` on next loop. When connection returns, `flush_buffer` drains the buffer. XDF write path is independent and continues. If buffer overruns 200 chunks, oldest chunks are silently dropped (deque maxlen) — XDF still has them, reconciliation backfills. |
| **DB crash and restart mid-session** | Same as above — connection drop, buffer, reconnect when DB is back. |
| **Forwarder + DB both lost in the same window** | XDF backup is the source of truth. On next session_close, reconciliation detects the missing rows and backfills from XDF. |
| **Disk loss** | Undefined. No PITR, no off-host backup configured. Application backup (XDF) and DB both gone if they're on the same disk. See §5.4. |
| **Watchdog crash** | Undefined. The watchdog is the failsafe; nothing supervises it. Manual restart needed. |

**Status.** ⚠️ Process + DB + DB-connection failure handled. Disk + watchdog-of-the-watchdog deferred.

**Open.**
- Document each recovery procedure as a runnable runbook (commands the operator would type) before any real UCSF session.
- For watchdog supervision: in the MVP just check that the watchdog is running via a cron heartbeat. In Phase 4 the deployment runs the watchdog under systemd / Docker `restart: always`.

---

### §5.7 Trigger firing order  ✅

**Concept.** When multiple AFTER triggers exist on the same table for the same event, Postgres fires them in **alphabetical order by trigger name**. If two triggers' side effects depend on each other (e.g., trigger B reads what trigger A wrote), the alphabetical ordering matters and should be deliberate — typically by prefixing names with `01_`, `02_`, etc.

**In this pipeline.**

- The `sessions` table has two triggers:
  - `sessions_audit_trigger` (migration `020_audit_triggers.py:106-112`): AFTER **INSERT** FOR EACH ROW → `audit_trigger_full_func()`.
  - `sessions_watermark_trigger` (migration `024_watermark_trigger.py:104-108`): AFTER **UPDATE** FOR EACH ROW → `sessions_watermark_func()`.
- They fire on **different events** (INSERT vs UPDATE), so ordering doesn't bite today.
- All other audited tables (alert_events, echo_events, etc.) have only a single AFTER INSERT trigger.

**Status.** ✅ No collision today; documented for future.

**Open.**
- If you ever add a second AFTER UPDATE trigger on `sessions` (e.g., a "session_close enforcement" trigger), name it so the firing order is deliberate — prefix with `01_`, `02_`, etc. so the audit trail trigger runs first, then the side-effect trigger.

---

### §5.8 Schema version visibility at runtime  ⚠️

**Concept.** A running application that talks to a database should verify, at startup, that the schema version it expects matches the schema version the DB is actually on. Without this check, you can deploy new code against an un-migrated DB (and get cryptic "column doesn't exist" errors) or run old code against a newer DB (and silently corrupt new schema). The standard pattern: a migration tool writes a "current version" marker into the DB (Alembic uses the `alembic_version` table); the application reads that marker at startup and refuses to run if it doesn't match expectations.

**In this pipeline.**

- Migration `015_schema_version_metadata.py` creates `schema_version_log` — designed to capture, per session: `alembic_version`, `app_version`, `python_version`, `postgres_version`, `timescaledb_version`, `pgvector_version`, `mne_version`, `neurokit2_version`, `pylsl_version`, `recorded_at`.
- The migration's docstring (`015:49-52`) describes `capture/session_init/`
  writing one row to this table at session start, alongside the config snapshot
  audit event, using the current Alembic head and `APP_VERSION`.
- **Implementation update (2026-06-07):** `capture/session_init/workflow.py:create_session` now writes one `schema_version_log` row in the same transaction as the session row and signal metadata rows. It records the current Alembic script head, `settings.APP_VERSION`, Python version, `SELECT version()`, and TimescaleDB/pgvector extension versions from `pg_extension`.
- There is also no startup-time check that the live Alembic head matches the version `config/settings.py` was written against. The forwarder will happily run against an older or newer DB schema and discover the mismatch only when a write fails.

**Status.** ⚠️ Session-time schema provenance write implemented; tests and startup-time compatibility check remain open.

**Open.**
- Write follow-up tests for one `schema_version_log` row per `create_session`, rollback when provenance insert fails, populated Alembic/app/Postgres/extension fields, and optional library columns left `NULL`.
- Add a startup-time assertion: forwarder / batch / session_close all verify that the live `alembic_version` matches an expected value baked into `config/settings.py`; refuse to run if mismatched.
- Add this as a new rollup item.

---

## Tier 6 — Spec-vs-implementation compliance

Findings surfaced during the spec-driven TDD rewrite (2026-06-09). Tests were written from
`.correctless/specs/` as a black box; any divergence between spec text and shipped code is
recorded here. ✅ items had tests adapted; ❌ items have tests left red (report-only policy).

### §6.1 `create_session` pre-DB input validation  ❌

**Concept.** A spec-mandated pre-condition: the public API should validate its inputs and raise a domain error *before* acquiring any external resource (DB connection, file handle). This is the "fail-fast without side effects" principle — a caller that passes a bad compound name should get a `ValueError` immediately, not a `psycopg2` error after a TCP handshake.

**In this pipeline.**
- `session-init.md` R-002/R-003/R-004 state that `create_session` must raise `ValueError` for an invalid `compound`, a non-UUID-v4 `participant_id`, and an invalid `compound_dose_unit` — all *before* touching the DB.
- `capture/session_init/workflow.py:create_session` calls `settings.validate()` then immediately calls `psycopg2.connect(settings.DATABASE_URL)` (~line 79). No input validation runs before the connection is opened.
- There is also no `db_factory` seam, so the unit-test variants of R-001/R-002/R-003/R-004 cannot run without a live DB.

**Failing tests (2026-06-09).**

All three tests in `tests/capture_tests/session_init/test_unit.py::TestCreateSessionValidation`:

```
FAILED test_r002_invalid_compound_raises_before_db
FAILED test_r003_invalid_participant_uuid_raises_before_db
FAILED test_r004_invalid_dose_unit_raises
```

Each test passes an invalid argument and expects `ValueError` before any DB work. What actually happens:

1. `create_session` skips validation and opens a real DB connection.
2. It reaches `cur.execute(SESSION_INSERT, {...})` at `capture/session_init/workflow.py:83`.
3. The DB rejects the query with:

```
psycopg2.errors.UndefinedColumn:
    column "capture_source" of relation "sessions" does not exist
    LINE 4: capture_source, compound, compound_dose, compound_do...
                ^
```

This was a point-in-time failure from 2026-06-09. The active branch now
validates `compound`, `participant_id`, and `compound_dose_unit` before
`psycopg2.connect`, and the database has been rebuilt from the canonical
001→030 migration chain.

**Status.** ✅ Resolved in the Phase 2 branch; R-002, R-003, and R-004 now
exercise the intended fail-fast behavior.

**Open.**
- No remaining migration issue. A `db_factory` seam is optional testability
  work, not required for the current validation contract.

---

### §6.2 Proposed `capture_source` → `capture_mode` rename was reverted  ✅

**Concept.** An uncommitted database revision briefly renamed the established
capture-source fields. That revision was removed rather than adopted.

**In this pipeline.**
- `sessions.capture_source` is defined by migration 002.
- `session_signal_metadata.capture_source` is defined by migration 019.
- `config/settings.py` exposes `CAPTURE_SOURCE` with values `simulated` or
  `hardware`.
- `SIMULATION_MODE` remains the derived runtime convenience alias.
- The clean migration chain ends at 030 and contains no `capture_mode` or
  `device_type` columns.

**Status.** ✅ The proposed rename was reverted. `capture_source` /
`CAPTURE_SOURCE` is the canonical schema and runtime name.

**Open.**
- None.

---

### §6.3 `StreamResult` / `ReconciliationReport` computed vs stored fields  ✅

**Concept.** The spec implies that `StreamResult.gap` and `ReconciliationReport.is_reconciled` are computed properties derived from their sibling fields. The implementation stores them as plain dataclass fields that are populated by `build_report` at construction time.

**In this pipeline.**
- `batch/reconciliation/models.py`: `StreamResult(xdf_count, db_count, gap)` — `gap` is a positional argument, not `xdf_count - db_count`. `ReconciliationReport` carries `is_reconciled` as an explicit boolean field.
- The computation logic lives in `batch/reconciliation/backfill.py:build_report`, which calculates gap and is_reconciled and passes them in at construction.
- Integration test R-015 covers the `build_report` path end-to-end.

**Status.** ✅ Tests written to the real API; all pass. No behavioral difference visible from outside.

**Open.**
- Rollup #32: consider making `gap` a `@property` on `StreamResult` (`xdf_count - db_count`) and `is_reconciled` a `@property` on `ReconciliationReport` (`all(s.gap == 0 for s in streams.values())`). Eliminates the risk of passing an inconsistent `gap` value at construction. Minor refactor.

---

### §6.4 `centered_arc_window` empty-dict fallback  ✅

**Concept.** The spec's R-011 implied that passing an empty `widths_s` mapping to `centered_arc_window` should raise, treating it as a misconfiguration. The implementation treats it as "use canonical defaults," which is a more lenient and arguably more useful contract.

**In this pipeline.**
- `batch/arc/windows.py:centered_arc_window(echo_ts, name, width_s, widths_s={})` — an empty dict causes the function to fall back to the built-in canonical window widths (W1=30s, W2=120s, W3=300s). Only a non-empty dict that is *missing* the requested `name` key raises `KeyError`.

**Status.** ✅ Test adapted to the real contract; passes.

**Open.**
- Rollup #33: update `arc-windows.md` R-011 to document the actual fallback contract so future readers don't re-derive it.

---

## Open items rollup

| # | Area | Severity | Source | Status |
|---|---|---|---|---|
| 1 | Aborted-session watermark path | Design / Phase 5b | CLAUDE.md known issue #2 | 📝 deferred |
| 2 | `session_close` stuck in `'closing'` on reconciliation failure | Bug | bugs.md MED-04 | 📝 filed |
| 3 | `batch/reconciliation/db.py:fetch_session_meta` missing sponsor_id | Tenancy hardening | bugs.md LOW-01 | 📝 filed |
| 4 | `versions/` ↔ `optional_governance/` future activation collision | Design note | this doc §1.7 | 🔍 known, documented |
| 5 | Integrity log written in separate transaction from samples | Tamper-evidence gap | bugs.md MED-06 | 📝 filed |
| 6 | Integrity log NOT written during buffer-flush path | Tamper-evidence gap | bugs.md MED-05 | 📝 filed |
| 7 | XDF write-failure visibility | Reconciliation safety | bugs.md MED-09 | 📝 filed |
| 8 | `watchdog.db.log_restart` connection leak | Resource hygiene | bugs.md MED-03 | 📝 filed |
| 9 | psycopg2.Error path drops chunks instead of retrying deadlock/serialization | Error handling | bugs.md MED-07 + LOW-04 | 📝 filed |
| 10 | Cursor leak on exception (raw `cur = conn.cursor()` form) | Hygiene | this doc §2.4 | 📝 new |
| 11 | Full SCHEMA.md ↔ migration cross-check (001–030) | Doc drift sweep | this doc §1.7 | 🔍 pending |
| 12 | `audit_trigger_smart_func` matches live DB | Deployment | CLAUDE.md known issue #3 | 🔍 deployment-side |
| 13 | `row_to_json` PII exclusion if any real-PII column ever lands | Future-proofing | CLAUDE.md known issue #4 | 🔍 conditional |
| 14 | Hypertable compression + backfill procedure documented | Operational doc | CLAUDE.md known issue #5 / this doc §4.2 | 📝 deferred |
| 15 | `flush_buffer` time budget on shutdown | Bug / shutdown safety | bugs.md MED-08 | 📝 filed |
| 16 | watchdog `time.sleep(delay)` not SIGTERM-interruptible | Hygiene | bugs.md LOW-03 | 📝 filed |
| 17 | `echo_events` missing UNIQUE on natural key | Constraint coverage | bugs.md LOW-02 | 📝 filed |
| 18 | `biosignal_integrity_log` UNIQUE for idempotent reconciliation | Constraint coverage | this doc §1.5 | 📝 new |
| 19 | EXPLAIN ANALYZE spot-check on real session data | Index validation | this doc §1.6 | 🔍 pending |
| 20 | Retention policy for old session chunks | Operational doc | this doc §4.4 | 📝 deferred (MVP scope) |
| 21 | DB role / privilege architecture | Security / deployment | CLAUDE.md known issue #1 / this doc §5.1 | ❌ required before UCSF |
| 22 | TLS in transit — `sslmode=` not set in DSN | Security / deployment | this doc §5.2 | ⚠️ document for prod |
| 23 | `pg_dump` automation + DR procedure | Operational / DR | this doc §5.4 | ⚠️ deferred to Phase 4 |
| 24 | Disk capacity monitoring + alerting | Operational | this doc §5.5 | ⚠️ deferred |
| 25 | Failure recovery runbooks documented | Operational | this doc §5.6 | 📝 needed before UCSF |
| 26 | `schema_version_log` is never populated by app code | Bug | this doc §5.8 | ⚠️ implementation added 2026-06-07; tests still needed |
| 27 | Startup-time check that live Alembic head matches expected | Operational safety | this doc §5.8 | 📝 new |
| 28 | Continuous aggregates evaluated when ARC batch becomes latency-bound | Performance / future | this doc §4.3 | 📝 deferred |
| 29 | Vault / rotation story for DATABASE_URL secret | Security / deployment | this doc §5.3 | 📝 deferred to Phase 4+ |
| 30 | `create_session` pre-DB validation | Spec compliance / testability | this doc §6.1 | ✅ resolved |
| 31 | Proposed capture-mode field rename | Spec compliance / doc | this doc §6.2 | ✅ reverted; `capture_source` retained |
| 32 | `StreamResult.gap` / `ReconciliationReport.is_reconciled` as stored vs computed fields | Spec compliance / design | this doc §6.3 | 📝 consider @property refactor |
| 33 | `arc-windows.md` R-011 documents wrong raise contract for empty `widths_s` | Spec compliance / doc | this doc §6.4 | 📝 update spec to match code |

---

## Verification log

| Date | Verified by | Item | Result |
|---|---|---|---|
| 2026-05-31 | Claude Opus 4.7 (local session) | Cross-thread cursor sharing across `capture/` | No instances found. `Grep` for instance-stashed conn/cursor + cross-reference of every threaded entity. |
| 2026-06-11 | Codex docs audit | Migration chain integrity (versions/) | Unbroken 001 → 030. `optional_governance/` is a deliberate parallel tree not walked by Alembic. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Tenancy filter coverage in `capture/` | All 9 session-touching SELECT/UPDATE sites confirmed to include `AND sponsor_id = %s`. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Audit trigger function (020) | Function definition matches docs. PL/pgSQL IF/ELSE on `TG_TABLE_NAME` (avoids SQL CASE eager-eval bug). |
| 2026-05-31 | Claude Opus 4.7 (local session) | Watermark trigger function (024) | Fires only on `NEW.status != OLD.status`. `'closed'` → `watermark_verified`, `'failed'` → `watermark_failed`. |
| 2026-05-29 | Ultraplan cloud session | bugs.md report | Produced full file-by-file bug review with 2C/1H/12M/9L/4I findings. |
| 2026-05-29 | Local session | bugs.md HIGH-01 fix | `b4d3111`: `run_stream_thread` catches RuntimeError, sets stop_event, logs CRITICAL. 65 tests pass. |
| 2026-05-29 | Local session | session_close imports clean | `uv run python -m capture.session_close --help` succeeds — both Criticals from bugs.md pre-resolved. |
| 2026-05-29 | Ultraplan cloud session | `2dab714 fix(security): harden metadata logging and static checks` | PII guard in logger, HTML escape in XDF metadata, `sql.Identifier` for dynamic table names. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Concurrency / threading model (§2.2) | 5 worker threads under forwarder (4 StreamThread + 1 ECHOThread). Shared state: XDFWriter (lock), stop_event (atomic), logger (thread-safe). No cross-thread DB state. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Hypertable chunk sizing (§4.1) | All 4 biosignal hypertables use `chunk_time_interval = INTERVAL '1 hour'` partitioned on `db_insert_time`. Compression policy at 1-day age (013). |
| 2026-05-31 | Claude Opus 4.7 (local session) | Index health (§1.6) | 023 covers core tables; 025, 026, 027, 028 each add their own indexes. Composite `(session_id, lsl_timestamp DESC)` is the universal biosignal access index. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Constraint coverage (§1.5) | CHECK + NOT NULL comprehensive. UNIQUE gap on `echo_events` and `biosignal_integrity_log` natural-key composites — filed in rollup. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Timezone consistency (§3.8) | All persisted timestamps `TIMESTAMPTZ NOT NULL DEFAULT NOW()` — zero bare TIMESTAMP. Application: zero naive `datetime.now()` in `capture/`. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Transactions & isolation level (§1.3) | `autocommit = False` set on every connection; isolation level is Postgres default `READ COMMITTED`. Documented as the contract. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Schema version visibility (§5.8) | `schema_version_log` table exists (migration 015) but **never populated** — 0 hits for `schema_version_log` / `alembic_version` in `capture/`, `batch/`, `ingestion/`. Filed as rollup #26 + #27. |
| 2026-06-07 | Codex | Schema version visibility (§5.8) | Implemented `schema_version_log` write in `capture.session_init.create_session`; follow-up tests still need to be written. Startup-time compatibility check remains open. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Trigger firing order (§5.7) | `sessions` has 2 triggers but different events (INSERT vs UPDATE). No collision. |
| 2026-05-31 | Claude Opus 4.7 (local session) | TLS in transit (§5.2) | `DATABASE_URL` in `.env.example` lacks `sslmode=`. Localhost-safe today; production needs explicit `require`+. |
| 2026-05-31 | Claude Opus 4.7 (local session) | Secrets management (§5.3) | `.env` + `python-dotenv` + `.gitignore` + pre-commit `no-env-files` hook. Chain is intact for MVP scope. |

---

## How to update this doc

When you fix or verify something:

1. Update the **status emoji** + **Last verified** date in the relevant tier's at-a-glance row.
2. Update the **Status.** line at the bottom of the section.
3. Add a row to the **Verification log** at the bottom with what you did and the result.
4. If a fix lands, mark the corresponding rollup item ✓ or remove it.
5. If a new concept comes into scope, add a section with the standard template (Concept / In this pipeline / Status / Open) in the right tier, then add a row to the tier's at-a-glance table and to the topic→section index at the bottom.

The doc is tracked in-repo so it travels with the branch. When you cut the "final Phase 2" branch, carry the verification log forward — don't reset it. Repo is private; deployment will go to a separate public repo, so review/health content here is intentional and safe to commit.

---

## Index — review topic → section

Use this to jump to whichever concern you're studying.

| Topic | Tier | Sections |
|---|---|---|
| Concurrency | 2 | §2.2 (threading model) · §2.1 (cursor safety) · §2.3 (deadlock retry) |
| Logic | external | bugs.md (Ultraplan cloud report, 2C/1H/12M/9L/4I) · §2.3 (DB error-handling logic) |
| SQL injection | 1 | §1.4 (every site uses `%s`; `sql.Identifier` for dynamic table names post `2dab714`) |
| Threading | 2 | §2.2 (thread map, ordering, signal hazards, GIL) · §2.1 (cursor safety) |
| Security | 3 + 5 | §3.1 (audit triggers) · §3.5 (tenancy) · §3.6 (pseudonymous IDs + PII guard) · §5.1 (roles) · §5.2 (TLS) · §5.3 (secrets) |
| Connection pooling | 1 | §1.2 (`n/a` — design decision, threshold to revisit documented) |
| Migration integrity | 1 | §1.7 (chain unbroken, `optional_governance` parallel tree, up/down symmetry) |
| Index health | 1 | §1.6 (per-table coverage in `023`, later migrations add their own) |
| Constraint coverage | 1 | §1.5 (CHECK inventory across `002`–`030`, FK list, UNIQUE gaps) |
| Timezone consistency | 3 | §3.8 (all `TIMESTAMPTZ`; zero naive `datetime.now()`; `time.time()` in xdf/samples.py explained) |
| Hypertable chunk sizing | 4 | §4.1 (1-hour interval on `db_insert_time`, expected row counts per chunk, compression at 1-day age) |
| Transactions / isolation | 1 | §1.3 (`autocommit=False` + READ COMMITTED) |
| Connection lifecycle | 1 | §1.1 (per-thread open + try/finally close) |
| Deadlock + serialization | 2 | §2.3 (transient retry path missing for non-OperationalError) |
| Cursor leak | 2 | §2.4 (two raw-cursor sites filed) |
| Audit trail | 3 | §3.1 (triggers-only writes, `audit_trigger_full_func()`) |
| Watermark / batch gating | 3 | §3.2 (closed → watermark_verified, failed → watermark_failed) |
| Tamper-evidence | 3 | §3.3 (chunk hashes, two structural gaps filed) |
| XDF reconciliation parity | 3 | §3.4 (XDF first, then DB; backfill at close) |
| Tenancy enforcement | 3 | §3.5 (capture/ covered; batch/ has LOW-01 gap) |
| Pseudonymous IDs | 3 | §3.6 (schema + logger + XDF all enforce) |
| Two-timestamp invariant | 3 | §3.7 (lsl_timestamp vs db_insert_time, never collapsed) |
| Compression | 4 | §4.2 (auto-compress at 1-day age, segmentby + orderby per table) |
| Continuous aggregates | 4 | §4.3 (not used; documented as deliberate non-use) |
| Retention policy | 4 | §4.4 (deferred for MVP scope) |
| DB roles / privileges | 5 | §5.1 (single superuser today — required before UCSF) |
| TLS in transit | 5 | §5.2 (no `sslmode=` in DSN; deployment-side gap) |
| Secrets management | 5 | §5.3 (.env + python-dotenv + pre-commit no-env-files hook) |
| Backup / DR | 5 | §5.4 (XDF parallel backup; no DB-level backup, no PITR) |
| Disk capacity / growth | 5 | §5.5 (~600 MB compressed per 4-h session; no monitoring) |
| Failure recovery | 5 | §5.6 (process / DB-connection / DB-crash recovery procedures) |
| Trigger firing order | 5 | §5.7 (alphabetical; sessions has 2 triggers on different events) |
| Schema version visibility | 5 | §5.8 (`schema_version_log` population implemented; tests + startup check still open) |

| Spec compliance — session-init validation | 6 | §6.1 (`create_session` validation now precedes DB connection) |
| Spec compliance — capture-source naming | 6 | §6.2 (proposed rename reverted; `capture_source` retained) |
| Spec compliance — reconciliation models | 6 | §6.3 (`gap` / `is_reconciled` stored vs computed) |
| Spec compliance — arc-windows fallback | 6 | §6.4 (empty `widths_s` falls back, doesn't raise) |

Add a row here whenever a new topic enters the doc or a new section gets created.
