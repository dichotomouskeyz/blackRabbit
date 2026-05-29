"""ECHO marker parsing and validation."""

from capture.echo_handler.models import (
    MARKER_FIELD_COUNT,
    MARKER_PREFIX,
    MARKER_SEPARATOR,
    VALID_ACTOR_ROLES,
    VALID_EVENT_TYPES,
    VALID_MANUAL_LABELS,
    VALID_ZONE_LABELS,
    ECHOEvent,
)


def valid_label_for_event(event_type: str, label: str) -> bool:
    if event_type == "manual_marker":
        return label in VALID_MANUAL_LABELS
    return label in VALID_ZONE_LABELS


def parse_echo_event(marker: str) -> ECHOEvent | None:
    if not marker.startswith(MARKER_PREFIX + MARKER_SEPARATOR):
        return None

    parts = marker.split(MARKER_SEPARATOR)
    if len(parts) != MARKER_FIELD_COUNT:
        return None

    _, event_type, actor_id, actor_role, zone_label = parts
    actor_id = actor_id.strip() or None

    if event_type not in VALID_EVENT_TYPES:
        return None
    if actor_role not in VALID_ACTOR_ROLES:
        return None
    if not valid_label_for_event(event_type, zone_label):
        return None

    return ECHOEvent(
        event_type=event_type,
        actor_id=actor_id,
        actor_role=actor_role,
        zone_label=zone_label,
    )


def parse_echo_marker(marker: str) -> dict | None:
    """Parse an ECHO pipe-delimited marker string into a field dict."""
    event = parse_echo_event(marker)
    return event.as_dict() if event else None
