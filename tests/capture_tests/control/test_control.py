"""Spec-driven tests for capture/control.py (capture-control.md).

Phase 2 — file-based stop-signal protocol. All unit tests; tmp_path-backed.
One test per R-xxx rule. Assertions derive from the spec text only.
"""

from pathlib import Path

import pytest

import capture.control as control
from capture.control import (
    clear_stop_request,
    request_stop,
    stop_request_path,
    stop_requested,
)

_SESSION_ID = "70000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(control.settings, "LOG_DIR", tmp_path, raising=False)
    return tmp_path


class TestPathConstruction:
    """capture-control.md — path construction.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_path_parent_and_filename(self, _log_dir):
        path = stop_request_path(_SESSION_ID)
        assert Path(path).parent == Path(_log_dir) / "control"
        assert _SESSION_ID in Path(path).name


class TestRequestStop:
    """capture-control.md — `request_stop`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r002_creates_parent_dirs(self, _log_dir):
        # control/ subdirectory does not exist yet.
        assert not (Path(_log_dir) / "control").exists()
        request_stop(_SESSION_ID)
        assert (Path(_log_dir) / "control").is_dir()

    def test_r003_writes_stop_text(self):
        path = request_stop(_SESSION_ID)
        assert Path(path).read_text(encoding="utf-8") == "stop\n"

    def test_r004_returns_created_path(self):
        path = request_stop(_SESSION_ID)
        assert Path(path) == Path(stop_request_path(_SESSION_ID))
        assert Path(path).exists()


class TestClearStopRequest:
    """capture-control.md — `clear_stop_request`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r005_removes_existing_file(self):
        path = request_stop(_SESSION_ID)
        assert Path(path).exists()
        clear_stop_request(_SESSION_ID)
        assert not Path(path).exists()

    def test_r006_noop_when_missing(self):
        # Must not raise when there is nothing to remove.
        assert clear_stop_request(_SESSION_ID) is None


class TestStopRequested:
    """capture-control.md — `stop_requested`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r007_true_when_file_exists(self):
        request_stop(_SESSION_ID)
        assert stop_requested(_SESSION_ID) is True

    def test_r008_false_when_file_absent(self):
        assert stop_requested(_SESSION_ID) is False
