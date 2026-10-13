# Agent Context — untitled_biometric_platform-1a

> Last updated: 2026-06-12
>
> Detailed invariants and trust boundaries live in
> [`.correctless/ARCHITECTURE.md`](ARCHITECTURE.md).

## What This Project Does

Local research-tool MVP for labs studying neuro-behavioral sessions. Captures synchronized
physiology (EEG, HRV, EDA, respiration via APEX) and behavioral context (manual zone/marker
events via ECHO) through Lab Streaming Layer, writes to TimescaleDB with simultaneous XDF
backup, and runs post-session ARC convergence analysis.

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| Session init | `capture/session_init/` | Creates the active session, builds modality rows through `SignalMetadataRow`, and writes the schema version log in one transaction |
| LSL forwarder | `capture/forwarder/` | Reads LSL streams, writes XDF first, then inserts samples into per-modality TimescaleDB tables |
| ECHO handler | `capture/echo_handler/` | Records manual zone/marker events from LSL marker stream |
| Watchdog | `capture/watchdog/` | Supervises forwarder subprocess; MAX_RESTARTS=5, exponential backoff |
| Session close | `capture/session_close/` | Reconciles XDF vs DB counts, backfills gaps, closes/fails session, triggers ARC |
| ARC processor | `batch/arc/processor.py` | Post-session convergence: ECHO anchors → APEX response windows (W1/W2/W3), FDR, durable outputs |
| Logger | `capture/logger.py` | Structured JSON logger factory; PII blocklist enforced at serialization time |
| Settings | `config/settings.py` | All runtime config; loads `.env` at import, fails fast on missing required vars |
| Operator API | `api/` | Thin capability-gated FastAPI surface (M0 read/create only); wraps backend contracts; direct SQL on a SELECT-only role; blocked capabilities 409 before any DB call |
| Arc watchdog config | `config/arc_watchdog/` | TOML config for ARC windows, FDR params, anchor event definitions |
| Schema migrations | `untitledplatform_1a_db/db/alembic/` | Active migration chain — source of truth for schema |

## Design Patterns

- **Centralized logger**: `log = get_logger("process_name")` once at module level — never instantiate logging directly. Name is the process name (e.g. `"lsl_forwarder"`), not the module path. Example: `capture/forwarder/runtime.py`

- **Structured log fields**: pass extra context via `extra={}` dict — `log.info("msg", extra={"session_id": sid, "field": val})`. Logger serializes as JSON; PII fields (name, email, dob, token, etc.) are stripped before output.

- **Config access**: always `from config import settings` then `settings.VAR_NAME` — never `os.environ` or `os.getenv` directly in application code. All required vars fail fast at import time.

- **Named SQL parameters**: `%(name)s` style with psycopg2, values passed as dicts — `cursor.execute(SQL, row_dict)`. SQL strings stored as module-level constants in `sql.py` files. No ORM.

- **Dual timestamps always separate**: every biosignal row carries `lsl_timestamp` (when LSL captured it) and `db_insert_time` (when it landed in the DB). Never merge, alias, or omit either.

- **Tenancy on every biosignal row**: `site_id` and `sponsor_id` must be present on every row that carries session data. Application queries must respect these boundaries.

- **Private helpers with underscore**: internal functions and module-level constants not part of the public API use `_underscore_prefix`. Public API is re-exported from `__init__.py` via `__all__`.

- **Absolute imports only**: `from capture.forwarder.models import SessionConfig` — never relative imports.

- **Integration test marker**: tests requiring a live database are marked `@pytest.mark.integration`. Unit tests carry no marker and must not touch the DB.

- **Test constants with underscore prefix**: `_UNIT_CFG`, `_INT_SESSION` etc. Unit-test constants use `_UNIT_*`, integration constants use `_INT_*`. Shared fixtures live in `support.py` per test subdirectory.

- **Patchable factories via module-attribute access (api/)**: call injected factories through their owning module — `deps.get_readonly_connection()`, never `from api.deps import get_readonly_connection` — so test patches on `api.deps` rebind the call site (PAT-012).

## Common Pitfalls

- **Writing to `audit_events` directly**: database triggers own those rows — application code never inserts into `audit_events`. **Instead**: let the trigger fire on the target table write.

- **Merging `lsl_timestamp` and `db_insert_time`**: they measure different things and will diverge under clock drift. **Instead**: always carry both columns through to the insert.

- **Relative imports**: they break when modules are run directly and violate project convention. **Instead**: use absolute imports from the package root.

- **Schema changes outside Alembic**: hand-editing tables leaves the migration chain inconsistent. **Instead**: `uv run alembic revision --message "..."` and write the upgrade/downgrade explicitly.

- **Accessing config via `os.environ`**: bypasses validation and fail-fast logic in settings. **Instead**: `from config import settings` and use `settings.VAR_NAME`.

- **ARC mutating raw APEX/ECHO records**: ARC is a read-and-derive layer. **Instead**: ARC reads from biosignal tables and writes only to its own output tables (e.g. `arc_convergence_events`, `session_baselines`).

- **Broad `except Exception` in application logic**: masks errors silently. **Instead**: catch specific exceptions (`psycopg2.OperationalError`, `ValueError`, etc.) and log with `extra={}` before re-raising with `raise ... from exc`.

- **Logging PII fields**: the logger strips known PII field names at serialization, but relying on the blocklist is not a substitute for not logging it. **Instead**: use pseudonymous `participant_id` (UUID) only; never log name, DOB, email, address, etc.

## Quick Reference

| Need to... | Do this |
|------------|---------|
| Run all tests | `uv run pytest` |
| Run tests verbose | `uv run pytest -v` |
| Run integration tests only | `uv run pytest -m integration` |
| Run unit tests only | `uv run pytest -m "not integration"` |
| Run operator API tests | `uv run pytest tests/api_tests` |
| Run the operator API | `uv run uvicorn api.app:app --host 127.0.0.1 --port 8000` |
| Run coverage | `uv run pytest --cov` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type check | `uv run pyright` |
| Payload schema version | `settings.PAYLOAD_SCHEMA_VERSION` (default `"1.0"`) |
| New DB migration | `uv run alembic revision --message "..."` |
| Apply migrations | `uv run alembic upgrade head` |
| Find a spec | `.correctless/specs/{feature}.md` |
| Check architecture | `.correctless/ARCHITECTURE.md` |
| See known issues | `.correctless/antipatterns.md` |
| Arc watchdog config | `config/arc_watchdog_config.toml` |
