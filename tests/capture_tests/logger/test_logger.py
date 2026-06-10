"""Spec-driven tests for capture/logger.py (logger.md).

Phase 2 — structured JSON logging singleton. All unit tests; no DB.
One test per R-xxx rule. Assertions derive from the spec text only.
"""

import json
import logging

import pytest

from capture import logger as logger_mod
from capture.logger import get_logger, set_session_id


@pytest.fixture(autouse=True)
def _reset_session_id():
    yield
    set_session_id(None)


def _json_formatter(process_name):
    log = get_logger(process_name)
    for handler in log.handlers:
        fmt = handler.formatter
        if fmt is not None and type(fmt).__name__ == "_JsonFormatter":
            return fmt
    # Fall back to whatever formatter the first handler carries.
    return log.handlers[0].formatter


def _make_record(process_name="proc", msg="hello", **extra):
    record = logging.LogRecord(
        name=process_name,
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _format(process_name="proc", **extra):
    record = _make_record(process_name=process_name, **extra)
    return json.loads(_json_formatter(process_name).format(record))


class TestLoggerRegistry:
    """logger.md — logger registry.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_same_name_same_instance(self):
        assert get_logger("registry_a") is get_logger("registry_a")

    def test_r002_different_names_different_instances(self):
        assert get_logger("registry_b") is not get_logger("registry_c")

    def test_r003_propagate_is_false(self):
        assert get_logger("registry_d").propagate is False


class TestSessionIdInjection:
    """logger.md — session ID injection.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r004_session_id_present_after_set(self):
        set_session_id("11112222-3333-4444-5555-666677778888")
        assert _format()["session_id"] == "11112222-3333-4444-5555-666677778888"

    def test_r005_session_id_null_after_reset(self):
        set_session_id(None)
        assert _format()["session_id"] is None


class TestJsonFormat:
    """logger.md — JSON format.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r006_output_is_valid_json(self):
        # _format already calls json.loads; reaching here means it parsed.
        assert isinstance(_format(), dict)

    def test_r007_exact_core_fields(self):
        payload = _format()
        assert set(payload.keys()) == {
            "timestamp",
            "process_name",
            "level",
            "session_id",
            "message",
        }

    def test_r008_timestamp_is_iso8601_utc(self):
        from datetime import datetime

        payload = _format()
        # Parses as ISO 8601; tolerate trailing Z by normalising to +00:00.
        ts = payload["timestamp"].replace("Z", "+00:00")
        parsed = datetime.fromisoformat(ts)
        assert parsed.utcoffset() is None or parsed.utcoffset().total_seconds() == 0

    def test_r009_extra_field_appears(self):
        payload = _format(custom_field="present")
        assert payload["custom_field"] == "present"

    def test_r010_forbidden_field_dropped(self):
        payload = _format(email="leak@example.com")
        assert "email" not in payload

    def test_r011_record_builtins_not_forwarded(self):
        payload = _format()
        for builtin in ("pathname", "args", "levelno", "msg", "lineno"):
            assert builtin not in payload

    def test_r012_exc_info_yields_exception_field(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="proc",
                level=logging.ERROR,
                pathname=__file__,
                lineno=20,
                msg="failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        payload = json.loads(_json_formatter("proc").format(record))
        assert "exception" in payload
        assert "ValueError" in payload["exception"]


class TestDegradedSettings:
    """logger.md — degraded settings.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r013_missing_log_dir_returns_stderr_only(self, monkeypatch):
        monkeypatch.delattr(logger_mod.settings, "LOG_DIR", raising=False)
        log = get_logger("degraded_proc_unique")
        assert isinstance(log, logging.Logger)
        # Only the stderr handler survives when the file path cannot be built.
        assert len(log.handlers) == 1
