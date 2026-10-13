# Spec: Logger

## Metadata
- **Task**: logger
- **Intensity**: standard
- **Recommended-intensity**: standard
- **Intensity reason**: no security keywords, no TB-xxx overlap, no antipattern history
- **Override**: none

## What

`capture/logger.py` provides a JSON-structured logging singleton for all platform processes. Each call to `get_logger(process_name)` returns a `logging.Logger` that emits one JSON object per line to stderr and to a rotating file under `settings.LOG_DIR`. The same process name always returns the same logger instance (no duplicate handlers). A module-level `_session_id` is injected into every log record; it starts as `None` and is updated via `set_session_id()` once the session UUID is known. Fields whose keys appear in `_FORBIDDEN_LOG_KEYS` are silently dropped from the log payload to prevent PII leakage.

## Rules

### Logger registry — unit tests

- **R-001** [unit]: `get_logger(name)` called twice with the same name returns the exact same `logging.Logger` instance (identity check, not equality).

- **R-002** [unit]: `get_logger(name)` called with different names returns different logger instances.

- **R-003** [unit]: Loggers returned by `get_logger` have `propagate = False` — log records do not bubble up to the root logger.

### Session ID injection — unit tests

- **R-004** [unit]: After `set_session_id("some-uuid")`, the `session_id` field in formatted log records equals `"some-uuid"`.

- **R-005** [unit]: After `set_session_id(None)`, the `session_id` field in formatted log records is `null` (JSON null, Python `None`).

### JSON format — unit tests

- **R-006** [unit]: `_JsonFormatter.format` produces valid JSON — the output is parseable by `json.loads` without error.

- **R-007** [unit]: Every formatted record includes exactly the fields `timestamp`, `process_name`, `level`, `session_id`, and `message`.

- **R-008** [unit]: `timestamp` in the formatted output is an ISO 8601 UTC string derived from the log record's `created` time.

- **R-009** [unit]: Extra fields passed via `extra={}` that are not in `_RECORD_BUILTINS` appear in the formatted JSON payload.

- **R-010** [unit]: Extra fields whose key appears in `_FORBIDDEN_LOG_KEYS` are silently dropped and do not appear in the formatted JSON payload.

- **R-011** [unit]: Standard `LogRecord` attributes (fields in `_RECORD_BUILTINS`) are never forwarded as extra payload — only caller-supplied extra fields pass through.

- **R-012** [unit]: When `exc_info` is set on the record, the formatted JSON includes an `exception` field with the formatted traceback string.

### Degraded settings — unit test

- **R-013** [unit]: When `settings.LOG_DIR` raises `AttributeError` (settings not fully initialized), `get_logger` returns a working logger with only the stderr handler — no `AttributeError` propagates to the caller.

## Won't Do

- Test that the rotating file handler actually writes to disk — filesystem I/O is stdlib behavior, not business logic.
- Test that `maxBytes` and `backupCount` produce correct file rotation — that is `RotatingFileHandler` behavior.
- Test log levels below DEBUG — the logger is set to `DEBUG`; caller controls which level to emit.

## Risks

- **`_session_id` is module-level global** — `set_session_id` affects all loggers in the process. In multi-threaded tests, calling `set_session_id` in one test affects concurrent tests. Mitigation: tests that rely on `session_id` content should call `set_session_id(None)` in teardown, or mock the module-level `_session_id` directly.
- **`except AttributeError`** only covers the missing `settings.LOG_DIR` attribute. `OSError` from `log_dir.mkdir` (e.g., permission denied) propagates out of `get_logger` as an unhandled error — accepted for the MVP; production deployments should ensure `LOG_DIR` is writable before startup.

## Open Questions

- _(none)_
