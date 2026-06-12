# Architecture — untitled_biometric_platform-1a

> Last quick-scan: 2026-06-11

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Session init | `capture/session_init/` | Creates session anchor row + 4 modality metadata rows + schema version log in a single transaction |
| LSL forwarder | `capture/forwarder/` | Reads LSL streams, writes XDF first, then inserts per-modality samples into TimescaleDB |
| ECHO handler | `capture/echo_handler/` | Records manual zone/marker events from LSL marker stream into echo_events table |
| Watchdog | `capture/watchdog/` | Supervises forwarder subprocess; MAX_RESTARTS=5, exponential backoff |
| Session close | `capture/session_close/` | Reconciles XDF vs DB counts, backfills gaps, closes/fails session, triggers ARC |
| ARC processor | `batch/arc/processor.py` | Post-session convergence: ECHO anchors → APEX response windows (W1/W2/W3), FDR, durable outputs |
| XDF writer | `capture/xdf/` | Writes Lab Streaming Layer data to XDF backup format before DB insert |
| Logger | `capture/logger.py` | Structured JSON logger factory; PII blocklist enforced at serialization time |
| Settings | `config/settings.py` | All runtime config; loads `.env` at import, fails fast on missing/invalid vars via `validate()` |
| Schema migrations | `untitledplatform_1a_db/db/alembic/versions/` | Active migration chain — source of truth for schema |

## Design Patterns

### PAT-001: Centralized Logger
- Instantiate logger once at module level: `log = get_logger("process_name")`
- Name is the process name (e.g. `"lsl_forwarder"`), not the module path
- Never instantiate `logging.getLogger()` directly in application code
- Enforced by: code review; grep for `logging.getLogger`

### PAT-002: Config via Settings Module
- All runtime config accessed via `from config import settings` then `settings.VAR_NAME`
- Never `os.environ` or `os.getenv` directly in application code
- `settings.validate()` called at top of every `main()` before doing any work — fails fast with all errors at once
- Enforced by: grep for `os.environ`/`os.getenv` outside `config/settings.py`

### PAT-003: Named SQL Parameters
- `%(name)s` style with psycopg2, values passed as dicts — `cursor.execute(SQL, row_dict)`
- SQL strings stored as module-level constants in `sql.py` files alongside the module that uses them
- No ORM — raw psycopg2 only
- Violated when: f-strings or `%` formatting used in SQL, or SQL strings scattered inline in functions

### PAT-004: Dual Timestamps on Biosignal Rows
- Every biosignal row carries both `lsl_timestamp` (when LSL captured it) and `db_insert_time` (when it landed in DB)
- These are never merged, aliased, or omitted — they measure different things and diverge under clock drift
- `lsl_timestamp` is always a float (seconds since LSL epoch); `db_insert_time` is always a DB-side `NOW()`
- Violated when: either timestamp is omitted, or a single timestamp field is reused for both purposes

### PAT-005: Tenancy on Every Biosignal Row
- `site_id` and `sponsor_id` must be present on every row that carries session data
- Application queries must respect these boundaries — never cross-query across `site_id` or `sponsor_id`
- ARC batch reads are covered: ARC entry points accept `sponsor_id` and apply it to session-scoped reads
- Violated when: a biosignal row omits either field, or a query lacks a `WHERE site_id = %s` filter

### PAT-006: Session Write Atomicity
- Session creation (session anchor + metadata rows + schema version log) is a single transaction
- On any exception: rollback, close connection, re-raise — never leave partial session state in the DB
- `autocommit = False` on the connection; explicit `commit()` only after all writes succeed
- Violated when: individual inserts are committed separately, or `autocommit = True` is used

### PAT-007: Absolute Imports Only
- `from capture.forwarder.models import SessionConfig` — never relative imports (`from .models import ...`)
- Relative imports break when modules are run directly as scripts
- Violated by: any `from . import` or `from .. import` in application code

### PAT-008: Integration Test Marker
- Tests requiring a live database are marked `@pytest.mark.integration`
- Unit tests carry no marker and must not touch the DB
- CI runs `pytest -m "not integration"` — integration tests only run when `TEST_DATABASE_URL` is set
- Violated when: a unit test (no marker) opens a DB connection

### PAT-009: StreamThread Resource Ownership
- `StreamThread` owns its DB connection (`thread.conn`), LSL inlet
  (`thread.inlet`), and mutable `StreamThreadState`
- `StreamThreadState` contains the buffer, sample index, chunk count, last
  drift timestamp, and fatal error
- Stream helper functions receive the thread as their resource owner rather
  than passing the connection and inlet through each call
- Violated when: helper modules create competing mutable ownership or return a
  connection that the thread does not store

## Trust Boundaries

### TB-001: Environment → Application Config
- **Crosses**: `.env` file / OS environment variables → `config/settings.py` → application runtime
- **Invariant**: All environment variable reads go through `config/settings.py`. No application module reads env vars directly. `settings.validate()` is the enforcement gate — called before any session work begins.
- **Violated when**: any module outside `config/settings.py` calls `os.environ`, `os.getenv`, or `dotenv.load_dotenv` directly.

### TB-002: LSL Streams → DB Write Path
- **Crosses**: External LSL stream data (hardware or simulator) → forwarder → TimescaleDB
- **Invariant**: LSL sample data is written to XDF backup first, then to DB. Both timestamps (lsl_timestamp, db_insert_time) are always carried. The forwarder never skips the XDF write.
- **Violated when**: DB insert happens before XDF write, or either timestamp is omitted from a biosignal row.

### TB-003: ARC Batch Reads → Tenant-Scoped Session Data
- **Crosses**: ARC batch entry points → ECHO/APEX/session tables
- **Invariant**: ARC session reads accept `sponsor_id` and filter by it. ARC
  remains read-and-derive and does not mutate raw APEX or ECHO records.
- **Violated when**: an ARC query reads session-scoped data using only
  `session_id`, or derived processing bypasses the sponsor boundary.

## Conventions

- Python 3.12+; `uv` manages dependencies and task running
- `ruff` for lint and format; `pyright` for type checking
- Test constants: `_UNIT_*` for unit-test fixtures, `_INT_*` for integration fixtures
- `participant_id` is always a UUID — never store or accept raw PII
- Schema changes only through Alembic: `uv run alembic revision --message "..."`
- Never write directly to `audit_events` — database triggers own those rows
- ARC is read-and-derive only — never mutates raw APEX/ECHO records
- `compound` values must come from `VALID_COMPOUNDS`; dose units from `VALID_DOSE_UNITS`

## Known Limitations

- No live safety monitor in MVP (deferred)
- No real-time SQI monitor in MVP (deferred)
- No web UI — CLI/notebook surface only (Phase 4b)
- `jq` required for workflow-advance.sh state machine but not installed by default on Windows
