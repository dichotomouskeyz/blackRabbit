"""Validation for GET /sessions query filters (session-query SQ-001/SQ-002).

Every filter is validated here, before any database connection, and arrives in
the read SQL only as a bound parameter (SQ-003).
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from capture.session_init.constants import VALID_COMPOUNDS

# The session_status enum (migration 002).
SESSION_STATUSES = ("initializing", "active", "closing", "closed", "failed")

DEFAULT_LIMIT = 200
MAX_LIMIT = 500

_SESSION_PREFIX_RE = re.compile(r"^[0-9a-f-]{1,36}$")


class FilterError(ValueError):
    """A rejected filter, carried to the structured 422 body."""

    def __init__(self, field: str, message: str, valid_choices=None):
        super().__init__(message)
        self.field = field
        self.message = message
        self.valid_choices = valid_choices


@dataclass(frozen=True)
class SessionFilters:
    session_prefix: str | None = None
    participant_id: str | None = None
    status: str | None = None
    compound: str | None = None
    created_from: datetime | None = None
    created_before: datetime | None = None
    limit: int = DEFAULT_LIMIT

    def as_params(self) -> dict:
        """Bound parameters for SESSIONS_LIST_SQL."""
        return {
            "session_prefix": self.session_prefix,
            "participant_id": self.participant_id,
            "status": self.status,
            "compound": self.compound,
            "created_from": self.created_from,
            "created_before": self.created_before,
            "limit": self.limit,
        }


def _clean(value: str | None) -> str | None:
    """The trimmed value, or None when it is absent or blank."""
    if value is None:
        return None
    text = value.strip()
    return text or None


def _instant(field: str, text: str) -> datetime:
    """An ISO date (UTC midnight) or a datetime that carries a UTC offset."""
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=UTC)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FilterError(field, f"{field} must be an ISO 8601 date or datetime") from exc
    if parsed.tzinfo is None:
        raise FilterError(field, f"{field} must include a UTC offset, such as Z or -07:00")
    return parsed


def parse_session_filters(
    *,
    session_id: str | None = None,
    participant_id: str | None = None,
    status: str | None = None,
    compound: str | None = None,
    created_from: str | None = None,
    created_before: str | None = None,
    limit: str | int | None = None,
) -> SessionFilters:
    """Validate raw query values into SessionFilters, or raise FilterError."""
    prefix = _clean(session_id)
    if prefix is not None:
        prefix = prefix.lower()
        if not _SESSION_PREFIX_RE.fullmatch(prefix):
            raise FilterError(
                "session_id", "session_id must be 1 to 36 hexadecimal characters or hyphens"
            )

    pid = _clean(participant_id)
    if pid is not None:
        try:
            pid = str(uuid.UUID(pid))
        except ValueError as exc:
            raise FilterError("participant_id", "participant_id must be a valid UUID") from exc

    st = _clean(status)
    if st is not None and st not in SESSION_STATUSES:
        raise FilterError("status", "unknown status", list(SESSION_STATUSES))

    cmp = _clean(compound)
    if cmp is not None and cmp not in VALID_COMPOUNDS:
        raise FilterError("compound", "unknown compound", list(VALID_COMPOUNDS))

    from_text = _clean(created_from)
    before_text = _clean(created_before)
    start = None if from_text is None else _instant("created_from", from_text)
    end = None if before_text is None else _instant("created_before", before_text)
    if start is not None and end is not None and start >= end:
        raise FilterError("created_before", "created_before must be later than created_from")

    lim = DEFAULT_LIMIT
    if limit is not None and str(limit).strip() != "":
        try:
            lim = int(str(limit).strip())
        except ValueError as exc:
            raise FilterError("limit", f"limit must be an integer from 1 to {MAX_LIMIT}") from exc
        if not 1 <= lim <= MAX_LIMIT:
            raise FilterError("limit", f"limit must be an integer from 1 to {MAX_LIMIT}")

    return SessionFilters(
        session_prefix=prefix,
        participant_id=pid,
        status=st,
        compound=cmp,
        created_from=start,
        created_before=end,
        limit=lim,
    )
