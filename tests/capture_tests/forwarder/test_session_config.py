"""Spec-driven tests for forwarder SessionConfig (forwarder.md R-010, R-011).

Phase 2 — frozen session config with UUID validation. All unit tests; no DB.
Assertions derive from the spec text only.
"""

import dataclasses

import pytest

from capture.forwarder.models import SessionConfig
from tests.capture_tests.forwarder.support import (
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


def _cfg(**over):
    kwargs = dict(
        session_id=SESSION_ID,
        participant_id=PARTICIPANT_ID,
        site_id=SITE_ID,
        sponsor_id=SPONSOR_ID,
        eeg_channel_names=None,
    )
    kwargs.update(over)
    return SessionConfig(**kwargs)


class TestSessionConfig:
    """forwarder.md — SessionConfig validation and immutability.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    @pytest.mark.parametrize(
        "field",
        ["session_id", "participant_id", "site_id", "sponsor_id"],
    )
    def test_r010_invalid_uuid_raises(self, field):
        with pytest.raises(ValueError):
            _cfg(**{field: "not-a-uuid"})

    def test_r011_is_frozen(self):
        cfg = _cfg()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.session_id = SITE_ID
