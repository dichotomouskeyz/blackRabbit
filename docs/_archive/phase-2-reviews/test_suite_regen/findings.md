# Test Suite Regen — Full-Suite Run Findings

**Repo:** `C:\Users\jahlo\untitled_biometric_platform-1a`
**Branch:** `2R` (at `2d52336`)
**Date:** 2026-06-10
**Snapshot:** Point-in-time test and database audit as of 2026-06-10; later
Phase 2 changes may resolve individual findings.
**Command:** `uv run pytest` (testpaths `tests/`, `tests/_archive` ignored — pyproject.toml:38-44)
**Environment:** Python 3.12.10 via uv 0.11.19 · TimescaleDB in Docker (`untitledproject-db-local`, port 5435)

Companion doc to [db-health.md](../../../2R/db-health.md). Database-layer findings already tracked there are referenced by §, not restated.

**Status legend** (same as db-health.md): ✅ verified clean · ⚠️ partial / known caveat · ❌ broken / urgent · 📝 deferred / filed only

---

## 1. Run summary

Three runs, because the environment changed mid-session:

| Run | Environment | Result |
|---|---|---|
| 1 | Docker down → test DB unreachable | 3 failed · 242 passed · **66 skipped** · 17.6s |
| 2 | DB up, schema = repaired phantom state (stamped `032`) | **46 failed** · 261 passed · 4 skipped · 5.1s |
| 3 | DB rebuilt from clean chain 001→030 (see §4) | **46 failed** · 261 passed · 4 skipped · 4.3s |

Runs 2 and 3 are **identical** — every failure is test-vs-implementation drift, none are schema- or data-dependent. The rebuild (§4) changed nothing behaviorally, which is the point: it proves the repaired DB and the clean-chain DB are equivalent.

311 tests collected, all from `tests/capture_tests/` (per-package: arc 108, xdf 33, reconciliation 27, session_close 24, echo_handler 22, forwarder 21, settings 21, session_init 17, watchdog 15, logger 13, control 10).

---

## 2. Skips — with reasons cited

### Run 1 (66 skips)

- **62 × DB-gated tests**: `TEST_DATABASE_URL database is unavailable: connection to server at "localhost", port 5435 failed: Connection refused`. Root cause: Docker Desktop was not running. The conftest gate (`tests/conftest.py:38-71`) marks every `integration`-marked test skipped when the DB is unreachable. Affected files: `arc/test_arc_processor.py` (9), `session_close/test_run.py` (13), `reconciliation/test_backfill.py` (8), `session_init/test_db.py` (6), `reconciliation/test_db.py` (6), `watchdog/test_db.py` (5), `echo_handler/test_integration.py` (5), `arc/test_arc_preflight.py` (5), `forwarder/test_chunk_drift.py` (4), `session_init/test_unit.py` (1).
- **4 × watchdog loop tests** (`watchdog/test_loop.py:51,66,69,72`): "watchdog loop harness symbols not importable; wire in Phase D" — deliberate placeholders, not failures.

### Runs 2–3 (4 skips)

Only the 4 Phase-D watchdog placeholders remain.

### Context: the phantom DB

The DB-unavailability in run 1 sits on top of a deeper history the user flagged: a Codex session on **2026-06-07** applied an **uncommitted post-030 "phantom" capture-mode revision** directly to the live DB that:

- renamed `sessions.capture_source` → `capture_mode`
- dropped `session_signal_metadata.capture_source`, added `device_type`
- replaced 8 per-modality electrode columns with 3 generic ones

Two uncommitted repair revisions dated 2026-06-09 reversed the damage. Resolution this session: both repair revisions were deleted and the DB was rebuilt — see §4.

---

## 3. Failures — 46, all test-vs-implementation drift

No implementation bug was *introduced* by anything tested here; every failure is the regenerated (spec-driven) tests encoding an API the implementation doesn't expose, plus two pre-known issues. Classes:

| # | Class | Tests | Evidence | Read |
|---|---|---|---|---|
| F1 | `run()`/`reconcile` path passed as `str`, impl calls `.exists()` on it | 13 — `session_close/test_run.py` (all) | `batch/reconciliation/xdf.py:36: AttributeError: 'str' object has no attribute 'exists'` | Tests pass `str`, impl expects `Path`. Type-contract drift. |
| F2 | ARC preflight arg order | 5 — `arc/test_arc_preflight.py` | `validate_arc_temporal_alignment() got multiple values for argument 'threshold_s'` | Positional/keyword mismatch vs spec. |
| F3 | ARC processor signatures | 7 — `arc/test_arc_processor.py` | `compute_session_baseline_rows() takes 2-3 positional args but 4 were given`; `load_echo_anchor_rows() got multiple values for 'anchor_filters'`; session id passed where a path is expected (`FileNotFoundError: 'b4000000-…'`) | Signature drift. |
| F4 | ECHO writer constructor | 5 — `echo_handler/test_integration.py` | `ECHOWriter.__init__() takes 1 positional argument but 2 were given` | Tests assume config-injected ctor; impl takes none. |
| F5 | Backfill row-builder kwargs | 5 — `reconciliation/test_backfill.py` | `_build_backfill_rows() got an unexpected keyword argument 'lsl_timestamp'`; one assert-shape mismatch (`{} == 0`) | Kwarg-name drift. |
| F6 | Reconciliation DB arg order | 3 — `reconciliation/test_db.py` | `UndefinedTable: relation "a3000000-…"` — session UUID interpolated as table name | Tests pass `(conn, session_id, table)`; impl expects table first (or vice versa). |
| F7 | Forwarder buffer constant | 4 — `forwarder/test_chunk_drift.py` | `module …stream_db has no attribute 'BUFFER_MAX_CHUNKS'` | Spec names a constant the impl never defined (buffer maxlen=200 is inline; cf. db-health §2.2). |
| F8 | session_init pre-DB validation | 3 — `session_init/test_unit.py` R-002/003/004 | `create_session` connects (`workflow.py:79`) before validating | **Known** — db-health §6.1, stays ❌. The only class that is an acknowledged *implementation* gap. |
| F9 | watchdog `log_restart` non-fatal contract | 1 — `watchdog/test_db.py` R-015 | raises `RuntimeError: Session … not found … compound is required` | **Known** — the test itself cites BUG-003; related to db-health §1.1 Open (MED-03 territory). |

F1–F7 (42 tests) need a decision per class: fix the test to match the implementation, or treat the spec as authoritative and change the implementation. That decision is out of scope for this run-and-document pass.

---

## 4. Migration chain cleanup (resolves the phantom-DB era)

User decision this session: the repair migrations are unwanted history; the DB holds no data worth preserving. Actions taken:

1. **Deleted** both untracked post-030 repair revision files; the committed chain already ended at `030_arc_failure_alert_type`.
2. **Dropped and recreated** `untitled_project_local`, ran `alembic upgrade head`.
3. **Discovered and fixed a real bug**: the fresh run failed at `019_session_signal_metadata` — `psycopg2.errors.DuplicateColumn: column "eeg_electrode_type" specified more than once`. The committed chain had **never been run from scratch**; the duplicate was masked because the live DB predated it. The second declaration (CHECK in `('ag_agcl','dry','other')`) was a copy-paste of the *EDA* electrode value set; the first (`('wet','dry','sponge','other','unknown')`) matches `capture/session_init/cli.py:56` and SCHEMA.md. Removed the duplicate declaration from 019. The duplicate's docstring rationale (wet Ag/AgCl gel electrodes have a ~100x lower noise floor than dry; the SQI monitor applies different impedance thresholds per electrode type) was **preserved by merging it into the surviving `eeg_electrode_type` docstring entry** — it matters for the Phase 3b SQI implementation.
4. **Re-ran the chain**: clean 001 → 030, head = `030_arc_failure_alert_type`.

Everything those post-030 repair revisions carried already lives in the canonical migrations — nothing was lost by deleting them:

- `capture_source TEXT NOT NULL DEFAULT 'simulated' CHECK IN ('simulated','hardware')` on **sessions** → `002_sessions.py:124` ✅
- same on **session_signal_metadata** → `019_session_signal_metadata.py` ✅
- the 8 granular per-modality electrode columns (`eeg_sensor_form`, `eeg_electrode_system`, `eeg_electrode_type`, `hrv_electrode_placement`, `hrv_electrode_type`, `eda_electrode_placement`, `eda_electrode_type`, `eda_skin_prep`) + `eeg_skin_prep` → all in `019`, consumed by `capture/session_init/metadata.py` / `sql.py:25` ✅

Rebuilt-schema verification (information_schema + pg_constraint):

- `capture_source` present on both tables; `capture_mode` / `device_type` present **nowhere** ✅
- CHECK constraints now correctly named `sessions_capture_source_check` / `session_signal_metadata_capture_source_check` — the repaired DB had carried a `sessions_capture_mode_check` scar (constraint kept its phantom-era name through the column rename) ✅
- Test suite identical before/after rebuild (§1) ✅

---

## 5. DB metadata consistency across `capture/`

Static cross-check of every DB-touching site in the capture package against the rebuilt 001→030 schema (2026-06-10).

### ✅ Verified consistent

- **All 12 INSERT statements** in `capture/` reference only columns that exist in the rebuilt schema, verified programmatically via `information_schema.columns`: `sessions` (12 cols), `session_signal_metadata` (33), `schema_version_log` (12), `echo_events` (10), `clock_drift_log` (10), `biosignal_integrity_log` (11), `alert_events` (13, two call sites: `session_close/db.py` + `watchdog/db.py`), and the four biosignal hypertables (`eeg_samples` 9, `hrv_samples` 10, `eda_samples` 10, `respiration_samples` 11).
- **Zero phantom-era references**: no `capture_mode` or `device_type` anywhere in `capture/`.
- **Value sets agree across all three layers** (DB CHECK in 002/019 ↔ `config/settings.py` validation ↔ `capture/session_init/cli.py` argparse choices) for: `capture_source` ('simulated','hardware'), `eeg_sensor_form`, `eeg_electrode_system`, `eeg_electrode_type` ('wet','dry','sponge','other','unknown' — confirming the kept 019 declaration is the right one), `hrv_signal_source`, `hrv_electrode_placement` (8 values), `hrv_electrode_type` (8 values), `eda_electrode_placement`, `eda_electrode_type`, `eda_skin_prep`, `eda_signal_source`.
- Settings defaults all fall inside their CHECK sets (e.g. `EEG_ELECTRODE_TYPE = 'unknown'` — settings.py:278).

### ⚠️ Gaps found

1. **`eeg_skin_prep` is an orphan column.** It exists in 019 (with CHECK + SQI-relevant docstring) but appears nowhere in `capture/`: no CLI flag (only `--eda-skin-prep` exists), no settings default, and it is absent from `_METADATA_INSERT` (`capture/session_init/sql.py:19-48`). It is always NULL. The SQI monitor (Phase 3b) will want it populated — wire it through cli → workflow → metadata → sql alongside the other EEG fields.
2. **EDA metadata has no settings fallback, unlike EEG/HRV.** `_eeg_metadata` and `_hrv_metadata` apply `arg or settings.X` defaults (`capture/session_init/metadata.py:87-89,112-113`), but `_eda_metadata` passes raw args through (`metadata.py:131-133`), and `config/settings.py` defines no `EDA_ELECTRODE_PLACEMENT` / `EDA_ELECTRODE_TYPE` / `EDA_SKIN_PREP`. EDA electrode provenance is NULL unless supplied per-run on the CLI — asymmetric with the other modalities and a silent provenance gap for SQI.

---

## 6. Cross-references into db-health.md (no content duplicated)

| Finding here | Feeds back into |
|---|---|
| F8 confirmed red against a live DB | db-health **§6.1** — no status change, still ❌ |
| 019 duplicate-column fix | db-health **§1.7** — chain symmetry intact; the chain listing should end at `030_arc_failure_alert_type` 🔍 |
| `CAPTURE_SOURCE` naming settled (column + settings agree) | db-health **§6.2** — unchanged ✅ |
| F9 / BUG-003 | db-health **§1.1 Open** (watchdog `log_restart`) |
| Schema CHECK/constraint behavior exercised by passing schema tests | db-health **§1.5** — UNIQUE gaps there remain untested here 📝 |

---

## 7. Structural / hygiene findings

- ⚠️ **`DATABASE_URL` and `TEST_DATABASE_URL` point at the same database** (`untitled_project_local` on 5435). The conftest rolls back per-test, but session-scoped fixtures (`restricted_role`) grant privileges that persist, and any committed write in a future test would land in the dev DB. Recommend a dedicated `untitledplatform_test` database.
- 📝 **Legacy test dirs are empty shells**: `tests/echo_handler`, `tests/echo_handler_test`, `tests/reconcile_test` contain only `__pycache__` leftovers; `tests/unit`, `tests/integration` only `.gitkeep`. Nothing is double-collected (the regen fully replaced them), but the husks invite confusion — delete the pycache dirs and either repurpose or remove the `.gitkeep` dirs.
- 📝 Stale `__pycache__` is from CPython **3.14** (`cpython-314` tags) while the project venv is 3.12.10 — further evidence those dirs are dead.

---

## 8. Open items

| # | Item | Status |
|---|---|---|
| 1 | Decide per failure-class F1–F7: fix tests vs change implementation (42 tests) | ❌ open |
| 2 | session_init pre-DB validation (F8, db-health §6.1) | ❌ open, pre-existing |
| 3 | watchdog `log_restart` non-fatal contract (F9 / BUG-003) | ⚠️ filed |
| 4 | Split `TEST_DATABASE_URL` onto a dedicated test database | ⚠️ recommended |
| 5 | Correct db-health §1.7 chain listing so the true head is `030` | 🔍 doc fix |
| 6 | Wire `eeg_skin_prep` through cli → metadata → sql (orphan column, §5 gap 1; SQI prerequisite) | ⚠️ filed |
| 7 | Add EDA settings defaults + `_eda_metadata` fallback symmetry (§5 gap 2) | ⚠️ filed |
| 8 | Delete legacy test-dir husks | 📝 hygiene |
| 9 | Wire watchdog loop harness (4 Phase-D skips) | 📝 deferred by design |
