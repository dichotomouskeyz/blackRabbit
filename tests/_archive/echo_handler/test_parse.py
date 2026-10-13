"""Unit tests for ECHO marker parsing and simulator marker shape."""

from capture.echo_handler.models import VALID_MANUAL_LABELS, VALID_ZONE_LABELS
from capture.echo_handler.parser import parse_echo_marker
from capture.marker_simulator import EMISSION_SEQUENCE, build_echo_marker


class TestParseEchoMarker:
    def test_valid_all_zone_labels(self):
        for zone in VALID_ZONE_LABELS:
            result = parse_echo_marker(f"ECHO|zone_enter|therapist_01|therapist|{zone}")
            assert result is not None
            assert result["zone_label"] == zone

    def test_valid_all_actor_roles(self):
        for role in ("therapist", "facilitator", "coordinator", "observer"):
            result = parse_echo_marker(f"ECHO|zone_enter|actor_01|{role}|arms_reach")
            assert result is not None
            assert result["actor_role"] == role

    def test_returns_all_expected_fields(self):
        result = parse_echo_marker("ECHO|zone_enter|therapist_01|therapist|in_room")
        assert result == {
            "event_type": "zone_enter",
            "actor_id": "therapist_01",
            "actor_role": "therapist",
            "zone_label": "in_room",
        }

    def test_strips_actor_id_whitespace(self):
        result = parse_echo_marker("ECHO|zone_enter|  therapist_01  |therapist|arms_reach")
        assert result is not None
        assert result["actor_id"] == "therapist_01"

    def test_wrong_prefix_returns_none(self):
        assert parse_echo_marker("MARKER|zone_enter|t|therapist|arms_reach") is None

    def test_missing_prefix_returns_none(self):
        assert parse_echo_marker("zone_enter|t|therapist|arms_reach") is None

    def test_too_few_fields_returns_none(self):
        assert parse_echo_marker("ECHO|zone_enter|therapist") is None

    def test_too_many_fields_returns_none(self):
        assert parse_echo_marker("ECHO|zone_enter|t|therapist|arms_reach|extra") is None

    def test_unknown_zone_label_returns_none(self):
        assert parse_echo_marker("ECHO|zone_enter|t|therapist|close_enough") is None

    def test_unknown_actor_role_returns_none(self):
        assert parse_echo_marker("ECHO|zone_enter|t|researcher|arms_reach") is None

    def test_unknown_event_type_returns_none(self):
        assert parse_echo_marker("ECHO|zone_change|t|therapist|arms_reach") is None

    def test_proximity_state_change_returns_none(self):
        assert parse_echo_marker("ECHO|proximity_state_change|t|therapist|arms_reach") is None

    def test_empty_actor_id_parses_with_null_actor(self):
        result = parse_echo_marker("ECHO|zone_enter||therapist|arms_reach")
        assert result is not None
        assert result["actor_id"] is None

    def test_empty_string_returns_none(self):
        assert parse_echo_marker("") is None

    def test_non_echo_lsl_marker_returns_none(self):
        assert parse_echo_marker("STIMULUS_ONSET") is None

    def test_valid_requested_event_types(self):
        examples = {
            "zone_enter": "ECHO|zone_enter|therapist_01|therapist|arms_reach",
            "zone_exit": "ECHO|zone_exit|therapist_01|therapist|arms_reach",
            "manual_marker": ("ECHO|manual_marker|coordinator_01|coordinator|dose_administration"),
        }

        for event_type, marker in examples.items():
            result = parse_echo_marker(marker)

            assert result is not None
            assert result["event_type"] == event_type

    def test_manual_marker_rejects_zone_label(self):
        assert parse_echo_marker("ECHO|manual_marker|c|coordinator|arms_reach") is None

    def test_zone_event_rejects_manual_label(self):
        assert parse_echo_marker("ECHO|zone_enter|t|therapist|session_note") is None


class TestSimulatorECHOMarkers:
    def test_simulated_echo_markers_parse_as_valid_echo_events(self):
        for event_type, actor_id, actor_role, label in EMISSION_SEQUENCE:
            marker = build_echo_marker(actor_id, actor_role, label, event_type)
            parsed = parse_echo_marker(marker)

            assert parsed == {
                "event_type": event_type,
                "actor_id": actor_id,
                "actor_role": actor_role,
                "zone_label": label,
            }

    def test_simulated_echo_sequence_exercises_requested_event_types(self):
        event_types = {event_type for event_type, _, _, _ in EMISSION_SEQUENCE}

        assert event_types == {"zone_enter", "zone_exit", "manual_marker"}

    def test_simulated_echo_sequence_uses_valid_schema_labels(self):
        for event_type, _, _, label in EMISSION_SEQUENCE:
            if event_type == "manual_marker":
                assert label in VALID_MANUAL_LABELS
            else:
                assert label in VALID_ZONE_LABELS
