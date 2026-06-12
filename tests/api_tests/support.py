"""Shared constants/helpers for operator-API tests (UUID prefix a9).

Conventions (AGENT_CONTEXT): `_UNIT_*` for unit fixtures, `_INT_*` for
integration fixtures. DB-backed tests are marked `@pytest.mark.integration`
and reuse the root `tests/conftest.py` db fixtures (db_conn/cursor/db_url).
"""

import re

# --- Fixed UUIDs (prefix a9) -------------------------------------------------
_INT_SPONSOR_A = "a9000000-0000-4000-8000-0000000000a1"
_INT_SITE_A = "a9000000-0000-4000-8000-0000000000a2"
_INT_SPONSOR_B = "a9000000-0000-4000-8000-0000000000b1"
_INT_SITE_B = "a9000000-0000-4000-8000-0000000000b2"
_INT_PARTICIPANT = "a9000000-0000-4000-8000-0000000000c1"
_INT_DEVICE = "a9000000-0000-4000-8000-0000000000d1"

# Sessions seeded in distinct watermark states (INV-016).
_INT_SESSION_VERIFIED = "a9000000-0000-4000-8000-000000010001"
_INT_SESSION_INPROGRESS = "a9000000-0000-4000-8000-000000010002"
_INT_SESSION_FAILED = "a9000000-0000-4000-8000-000000010003"
_INT_SESSION_NOTSTARTED = "a9000000-0000-4000-8000-000000010004"
# A verified session owned by sponsor B (must not appear for sponsor A).
_INT_SESSION_OTHER_SPONSOR = "a9000000-0000-4000-8000-000000010099"

_UNIT_VALID_COMPOUND = "psilocybin"

# A well-formed UUID used in path tests that should NOT reach the DB when the
# endpoint is capability-gated or when validation rejects sibling input.
_UNIT_VALID_SESSION_ID = "a9000000-0000-4000-8000-00000000ffff"
_UNIT_MALFORMED_SESSION_ID = "not-a-uuid"
_UNIT_SQLI_SESSION_ID = "1;DROP TABLE sessions;--"

WRITE_TOKEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|MERGE|UPSERT)\b",
    re.IGNORECASE,
)
READ_PREFIX_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def is_capability_unavailable_body(body: dict) -> bool:
    """True iff body matches the spec's capability-status contract shape."""
    if not isinstance(body, dict):
        return False
    if body.get("error") != "capability_unavailable":
        return False
    required = {"capability", "status", "blocked_reason", "gate"}
    return required.issubset(body.keys())
