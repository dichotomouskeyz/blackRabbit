"""Unit tests for ECHO marker parsing and simulator marker shape."""

from capture.echo_handler import VALID_ZONE_LABELS, parse_echo_marker
from capture.lsl_simulator import _ECHO_PROXIMITY_SEQUENCE, _build_echo_marker


class TestParseEchoMarker:
    def test_valid_all_zone_labels(self):
        for zone in VALID_ZONE_LABELS:
            result = parse_echo_marker(
                f"ECHO|proximity_state_change|therapist_01|therapist|{zone}"
            )
            assert result is not None
            assert result["zone_label"] == zone

    def test_valid_all_actor_roles(self):
        for role in ("therapist", "facilitator", "coordinator", "observer"):
            result = parse_echo_marker(
                f"ECHO|proximity_state_change|actor_01|{role}|arms_reach"
            )
            assert result is not None
            assert result["actor_role"] == role

    def test_returns_all_expected_fields(self):
        result = parse_echo_marker(
            "ECHO|proximity_state_change|therapist_01|therapist|in_room"
        )
        assert result == {
            "event_type": "proximity_state_change",
            "actor_id": "therapist_01",
            "actor_role": "therapist",
            "zone_label": "in_room",
        }

    def test_strips_actor_id_whitespace(self):
        result = parse_echo_marker(
            "ECHO|proximity_state_change|  therapist_01  |therapist|arms_reach"
        )
        assert result is not None
        assert result["actor_id"] == "therapist_01"

    def test_wrong_prefix_returns_none(self):
        assert (
            parse_echo_marker("MARKER|proximity_state_change|t|therapist|arms_reach")
            is None
        )

    def test_missing_prefix_returns_none(self):
        assert (
            parse_echo_marker("proximity_state_change|t|therapist|arms_reach") is None
        )

    def test_too_few_fields_returns_none(self):
        assert parse_echo_marker("ECHO|proximity_state_change|therapist") is None

    def test_too_many_fields_returns_none(self):
        assert (
            parse_echo_marker(
                "ECHO|proximity_state_change|t|therapist|arms_reach|extra"
            )
            is None
        )

    def test_unknown_zone_label_returns_none(self):
        assert (
            parse_echo_marker("ECHO|proximity_state_change|t|therapist|close_enough")
            is None
        )

    def test_unknown_actor_role_returns_none(self):
        assert (
            parse_echo_marker("ECHO|proximity_state_change|t|researcher|arms_reach")
            is None
        )

    def test_unknown_event_type_returns_none(self):
        assert parse_echo_marker("ECHO|zone_change|t|therapist|arms_reach") is None

    def test_empty_actor_id_returns_none(self):
        assert (
            parse_echo_marker("ECHO|proximity_state_change||therapist|arms_reach")
            is None
        )

    def test_empty_string_returns_none(self):
        assert parse_echo_marker("") is None

    def test_non_echo_lsl_marker_returns_none(self):
        assert parse_echo_marker("STIMULUS_ONSET") is None


class TestSimulatorECHOProximityMarkers:
    def test_simulated_echo_markers_parse_as_valid_proximity_events(self):
        for actor_id, actor_role, zone_label in _ECHO_PROXIMITY_SEQUENCE:
            marker = _build_echo_marker(actor_id, actor_role, zone_label)
            parsed = parse_echo_marker(marker)

            assert parsed == {
                "event_type": "proximity_state_change",
                "actor_id": actor_id,
                "actor_role": actor_role,
                "zone_label": zone_label,
            }

    def test_simulated_echo_sequence_exercises_near_and_departure_states(self):
        zones = [zone for _, _, zone in _ECHO_PROXIMITY_SEQUENCE]

        assert "arms_reach" in zones
        assert "in_room" in zones
        assert "leaving_room" in zones
        assert "out_of_room" in zones
        assert set(zones).issubset(VALID_ZONE_LABELS)

