"""INV-005 / INV-003 — no PII; closed response-field allowlist; UUID participant_id.

- POST /sessions with a non-UUID participant_id -> 422 (validated at API layer).
- API response models contain only allow-listed fields (no PII fields).
- INV-003 [unit]: api/ never inserts echo_events (closed-SQL scan backstop).
"""

import importlib
import pkgutil

import pytest

from tests.api_tests.support import (
    _UNIT_VALID_COMPOUND,
    READ_PREFIX_RE,
    WRITE_TOKEN_RE,
)


def _iter_api_sql_constants():
    """Yield (module_name, const_name, sql) for every uppercase *_SQL str
    constant across ALL submodules of the `api` package (QA-002 generic scan)."""
    import api

    for info in pkgutil.iter_modules(api.__path__, prefix="api."):
        mod = importlib.import_module(info.name)
        for name, val in vars(mod).items():
            if name.isupper() and name.endswith("SQL") and isinstance(val, str):
                yield info.name, name, val


# Fields that must NEVER serialize out of any api/ response model.
_PII_FIELDS = {
    "name",
    "first_name",
    "last_name",
    "email",
    "dob",
    "date_of_birth",
    "address",
    "phone",
    "ssn",
    "mrn",
}


@pytest.fixture
def no_db(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "psycopg2.connect",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("non-UUID participant_id reached a DB connection")
        ),
    )
    return calls


def test_non_uuid_participant_id_returns_422(client, no_db):
    # Tests INV-005 [unit-ish/integration]: non-UUID participant_id -> 422 at API layer.
    body = {
        "compound": _UNIT_VALID_COMPOUND,
        "participant_id": "not-a-uuid",
        "capture_source": "simulated",
    }
    resp = client.post("/sessions", json=body)
    assert resp.status_code == 422, (
        f"non-UUID participant_id must be rejected with 422, got {resp.status_code}"
    )


# B6: the spec-pinned response-field ALLOWLISTS keyed by endpoint
# (method, path-template). Each response model's field set must be a SUBSET of
# the pinned set for the row it serializes (a leaked/extra field fails). These
# are pinned against the spec Endpoint contract + RS-019 sessions columns.
_SESSIONS_ROW_ALLOWLIST = {"id", "status", "compound", "started_at", "closed_at", "created_at"}
_STATUS_ALLOWLIST = {"id", "status", "started_at", "closed_at", "watermark_state"}
_CAPABILITY_ROW_ALLOWLIST = {"capability", "endpoint", "status", "blocked_reason", "gate"}

# Endpoint -> (allowlist, is_row_wrapped). For list/row endpoints the response
# model may wrap rows (e.g. {sessions:[Row]} or [Row]); we discover the inner
# row model when the top-level model wraps a list of a nested model.
_ENDPOINT_ALLOWLIST = {
    ("GET", "/sessions"): _SESSIONS_ROW_ALLOWLIST,
    ("GET", "/sessions/{session_id}/status"): _STATUS_ALLOWLIST,
    ("GET", "/capabilities"): _CAPABILITY_ROW_ALLOWLIST,
}


def _iter_routes_with_models(app):
    """Yield (method, path, response_model) for routes carrying one."""
    for r in app.routes:
        model = getattr(r, "response_model", None)
        if model is None:
            continue
        methods = getattr(r, "methods", None) or set()
        path = getattr(r, "path", None)
        for m in methods:
            if m in {"HEAD", "OPTIONS"}:
                continue
            yield (m, path, model)


def _row_models_for(model):
    """Return candidate row models whose fields must be subset-checked.

    Handles a model that wraps a list (e.g. SessionsList{sessions: list[Row]} or
    a bare list[Row]) by descending into nested Pydantic models; also returns the
    model itself when it directly carries the row fields.
    """
    import typing

    found = []

    def _descend(m, depth=0):
        if depth > 4:
            return
        # Unwrap typing constructs (List[Row], Optional[Row], etc.).
        args = typing.get_args(m)
        if args:
            for a in args:
                _descend(a, depth + 1)
            return
        if isinstance(m, type) and hasattr(m, "model_fields"):
            found.append(m)
            for field in m.model_fields.values():
                ann = getattr(field, "annotation", None)
                if ann is not None and ann is not m:
                    _descend(ann, depth + 1)

    _descend(model)
    return found


def test_response_models_are_subset_of_pinned_allowlist(app):
    # Tests INV-005 [unit/integration]: discover response models from the ACTUAL
    # route `response_model` annotations (FastAPI route table) and assert each
    # model's field set is a SUBSET of the spec's pinned allowlist for that
    # endpoint. An allowlist, not a denylist: any leaked/extra field fails, and
    # extra='forbid' is required on every model.
    checked_any = False
    for method, path, model in _iter_routes_with_models(app):
        allow = _ENDPOINT_ALLOWLIST.get((method, path))
        if allow is None:
            continue
        row_models = _row_models_for(model)
        # The pinned row's fields must be carried by exactly one nested model.
        row_model = None
        for rm in row_models:
            fields = set(rm.model_fields.keys())
            if fields and fields <= allow:
                row_model = rm
                break
            # also accept a model whose field set IS the allowlist
            if fields == allow:
                row_model = rm
                break
        assert row_model is not None, (
            f"{method} {path}: no response model whose fields are a subset of the "
            f"pinned allowlist {sorted(allow)}; found models "
            f"{[(m.__name__, sorted(m.model_fields.keys())) for m in row_models]}"
        )
        fields = set(row_model.model_fields.keys())
        extra = fields - allow
        assert not extra, (
            f"{method} {path}: {row_model.__name__} leaks field(s) outside the "
            f"pinned allowlist {sorted(allow)}: {sorted(extra)}"
        )
        # No PII may appear even if the allowlist somehow admitted it.
        assert not (fields & _PII_FIELDS), (
            f"{row_model.__name__} leaks PII field(s): {fields & _PII_FIELDS}"
        )
        # extra='forbid' is structural enforcement (INV-005).
        for rm in row_models:
            assert rm.model_config.get("extra") == "forbid", (
                f"{rm.__name__} must set extra='forbid' (got {rm.model_config.get('extra')!r})"
            )
        checked_any = True

    assert checked_any, (
        "no response_model found on the pinned endpoints (GET /sessions, "
        "/sessions/{id}/status, /capabilities); GREEN must annotate routes with "
        "closed Pydantic response models"
    )


def test_api_modules_never_insert_echo_events():
    # Tests INV-003 / PRH-002 / PRH-001 [unit]: no api/ SQL constant writes
    # echo_events or audit_events. Scans ALL api.* submodules generically (QA-002)
    # so a future write/echo_events/audit-write in ANY module (incl. api.arc)
    # fails — not just the previously hardcoded module list.
    found = list(_iter_api_sql_constants())
    assert found, "api/ must expose read SQL as module-level *_SQL constants"

    # Must cover api.arc, which reads the trigger-owned audit_events table.
    discovered_mods = {mod for mod, _, _ in found}
    assert "api.arc" in discovered_mods, "generic scan must cover api.arc SQL constants (QA-002)"

    for mod_name, name, val in found:
        lowered = val.lower()
        # A WRITE to echo_events / audit_events in ANY api/ module fails. A
        # read-only SELECT/WITH that merely names audit_events (as api.arc does)
        # is allowed; an INSERT/UPDATE/DELETE touching either table is not.
        is_write = bool(WRITE_TOKEN_RE.search(val)) and not READ_PREFIX_RE.match(val)
        assert not (is_write and "echo_events" in lowered), (
            f"{mod_name}.{name} writes echo_events (PRH-002)"
        )
        assert not (is_write and "audit_events" in lowered), (
            f"{mod_name}.{name} writes audit_events (PRH-001)"
        )
        # read-only shape backstop (INV-002)
        if val.strip():
            assert READ_PREFIX_RE.match(val) and not WRITE_TOKEN_RE.search(val), (
                f"{mod_name}.{name} is not read-only: {val!r}"
            )
