"""Spec-driven tests for watchdog CLI + backoff (watchdog.md R-001..R-006).

Phase 2 — `parse_uuid`, `build_forwarder_cmd`, `restart_delay_s`. Unit tests;
no DB. Assertions derive from the spec text only.

NOTE (black-box): symbol locations are inferred from the spec. Phase D
resolves any import mismatch only.
"""

import argparse
import sys

import pytest

from capture.watchdog.cli import build_forwarder_cmd, parse_uuid
from capture.watchdog.models import RESTART_DELAY_MAX_S, WatchdogArgs
from capture.watchdog.runner import restart_delay_s
from tests.capture_tests.watchdog.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


class TestParseUuid:
    """watchdog.md — CLI parsing.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_invalid_uuid_raises(self):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_uuid("not-a-uuid")

    def test_r002_valid_uuid_returns_lowercase_canonical(self):
        upper = SESSION_ID.upper()
        assert parse_uuid(upper) == SESSION_ID.lower()


class TestBuildForwarderCmd:
    """watchdog.md — forwarder command.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r003_command_shape_and_flags(self):
        args = WatchdogArgs(
            session_id=SESSION_ID,
            participant_id=PARTICIPANT_ID,
            site_id=SITE_ID,
            sponsor_id=SPONSOR_ID,
        )
        cmd = build_forwarder_cmd(args)
        assert cmd[:3] == [sys.executable, "-m", "capture.lsl_forwarder"]
        for flag, value in (
            ("--session-id", SESSION_ID),
            ("--participant-id", PARTICIPANT_ID),
            ("--site-id", SITE_ID),
            ("--sponsor-id", SPONSOR_ID),
        ):
            assert flag in cmd
            assert cmd[cmd.index(flag) + 1] == value


class TestRestartBackoff:
    """watchdog.md — restart backoff.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r004_first_delay_is_five(self):
        assert restart_delay_s(1) == 5.0

    def test_r005_doubles_each_increment(self):
        assert restart_delay_s(2) == 10.0
        assert restart_delay_s(3) == 20.0

    def test_r006_capped_at_max(self):
        assert restart_delay_s(100) == RESTART_DELAY_MAX_S == 60.0
