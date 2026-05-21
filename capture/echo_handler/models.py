"""ECHO marker models and validation constants."""

from dataclasses import dataclass

MARKER_PREFIX = "ECHO"
MARKER_SEPARATOR = "|"
MARKER_FIELD_COUNT = 5

VALID_ZONE_LABELS: frozenset[str] = frozenset(
    {"arms_reach", "in_room", "leaving_room", "out_of_room"}
)
VALID_MANUAL_LABELS: frozenset[str] = frozenset(
    {"dose_administration", "session_note", "participant_note", "environmental_note"}
)
VALID_ACTOR_ROLES: frozenset[str] = frozenset(
    {"therapist", "facilitator", "coordinator", "observer"}
)
VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {"zone_enter", "zone_exit", "manual_marker"}
)


@dataclass(frozen=True)
class ECHOEvent:
    event_type: str
    actor_id: str
    actor_role: str
    zone_label: str

    def as_dict(self) -> dict[str, str]:
        return {
            "event_type": self.event_type,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "zone_label": self.zone_label,
        }
