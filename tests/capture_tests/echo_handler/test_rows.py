"""Spec-driven tests for ECHO row helpers (echo-handler.md R-009..R-012).

Phase 2 — `raw_marker_from_sample`, `build_echo_row`. All unit tests; no DB.
Assertions derive from the spec text only.

NOTE (black-box): `build_echo_row` config shape is inferred from the spec
(reads the four tenancy IDs). Phase D resolves any mismatch in `_cfg` only.
"""

from types import SimpleNamespace

from capture.echo_handler.rows import build_echo_row, raw_marker_from_sample
from tests.capture_tests.echo_handler.support import (
    LSL_TIMESTAMP,
    PARTICIPANT_ID,
    SESSION_ID,
    SITE_ID,
    SPONSOR_ID,
)


def _cfg():
    return SimpleNamespace(
        session_id=SESSION_ID,
        participant_id=PARTICIPANT_ID,
        site_id=SITE_ID,
        sponsor_id=SPONSOR_ID,
    )


class TestRawMarkerFromSample:
    """echo-handler.md — `raw_marker_from_sample`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r009_none_returns_none(self):
        assert raw_marker_from_sample(None) is None

    def test_r010_list_returns_first_element(self):
        assert raw_marker_from_sample(["ECHO|manual_marker|a|therapist|x"]) == (
            "ECHO|manual_marker|a|therapist|x"
        )

    def test_r011_non_string_value_returns_none(self):
        assert raw_marker_from_sample([123]) is None


class TestBuildEchoRow:
    """echo-handler.md — `build_echo_row`.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r012_merges_tenancy_timestamp_and_parsed(self):
        parsed = {
            "event_type": "manual_marker",
            "actor_id": None,
            "actor_role": "therapist",
            "zone_label": "dose_administration",
        }
        row = build_echo_row(_cfg(), parsed, LSL_TIMESTAMP)
        assert row["session_id"] == SESSION_ID
        assert row["participant_id"] == PARTICIPANT_ID
        assert row["site_id"] == SITE_ID
        assert row["sponsor_id"] == SPONSOR_ID
        assert row["lsl_timestamp"] == LSL_TIMESTAMP
        for key, value in parsed.items():
            assert row[key] == value
