import json
import logging

from capture.logger import _JsonFormatter


def test_json_formatter_drops_forbidden_extra_keys():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.email = "person@example.test"
    record.password = "not-for-logs"  # pragma: allowlist secret
    record.offset_ms = 42.1

    payload = json.loads(_JsonFormatter("test_process").format(record))

    assert payload["offset_ms"] == 42.1
    assert "email" not in payload
    assert "password" not in payload
