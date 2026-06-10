"""Spec-driven tests for ECHO marker parsing (echo-handler.md R-001..R-008).

Phase 2 — `parse_echo_marker`. All unit tests; no DB.
Assertions derive from the spec text only. Valid vocabularies are read from
the module constants so the tests do not hardcode label values.
"""

import pytest

from capture.echo_handler.parser import (
    VALID_ACTOR_ROLES,
    VALID_MANUAL_LABELS,
    VALID_ZONE_LABELS,
    parse_echo_marker,
)

_ROLE = sorted(VALID_ACTOR_ROLES)[0]
_MANUAL_LABEL = sorted(VALID_MANUAL_LABELS)[0]
_ZONE_LABEL = sorted(VALID_ZONE_LABELS)[0]


def _manual(actor_id="actor1", role=_ROLE, label=_MANUAL_LABEL):
    return f"ECHO|manual_marker|{actor_id}|{role}|{label}"


class TestParseEchoMarker:
    """echo-handler.md — parser.

    ASSERTION SOURCE: spec-only
    Model used for assertions: Claude (Fable 5), implementation source withheld.
    """

    def test_r001_non_echo_prefix_returns_none(self):
        assert parse_echo_marker("FOO|manual_marker|a|therapist|x") is None

    def test_r002_wrong_field_count_returns_none(self):
        assert parse_echo_marker("ECHO|manual_marker|a|therapist") is None
        assert parse_echo_marker("ECHO|manual_marker|a|therapist|x|extra") is None

    def test_r003_invalid_event_type_returns_none(self):
        assert parse_echo_marker(f"ECHO|not_an_event|a|{_ROLE}|{_MANUAL_LABEL}") is None

    def test_r004_invalid_actor_role_returns_none(self):
        assert parse_echo_marker(f"ECHO|manual_marker|a|not_a_role|{_MANUAL_LABEL}") is None

    def test_r005_invalid_manual_label_returns_none(self):
        assert parse_echo_marker(f"ECHO|manual_marker|a|{_ROLE}|definitely_invalid") is None

    @pytest.mark.parametrize("event_type", ["zone_enter", "zone_exit"])
    def test_r006_invalid_zone_label_returns_none(self, event_type):
        assert parse_echo_marker(f"ECHO|{event_type}|a|{_ROLE}|definitely_invalid") is None

    def test_r007_valid_marker_returns_dict(self):
        result = parse_echo_marker(_manual())
        assert isinstance(result, dict)
        assert set(result.keys()) >= {
            "event_type",
            "actor_id",
            "actor_role",
            "zone_label",
        }
        assert result["event_type"] == "manual_marker"
        assert result["actor_role"] == _ROLE
        assert result["zone_label"] == _MANUAL_LABEL

    @pytest.mark.parametrize("actor_id", ["", "   "])
    def test_r008_blank_actor_id_becomes_none(self, actor_id):
        result = parse_echo_marker(_manual(actor_id=actor_id))
        assert result is not None
        assert result["actor_id"] is None
