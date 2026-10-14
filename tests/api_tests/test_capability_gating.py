"""INV-013 + PRH-007 — blocked/scaffolded capabilities are non-executable.

Every non-`implemented` capability endpoint returns the structured 409
capability-status body unconditionally and first — before any input
validation, DB connection, or backend call. The scaffolded WebSocket refuses
the upgrade with a capability-status close reason.

Test approach: integration (raw TestClient, no agent), per INV-013 enforcement.
These are NOT marked @pytest.mark.integration because they MUST prove that
NO DB connection is opened — they patch the connection factory and the wrapped
backend contracts and assert-not-called.
"""

import json

import pytest

from tests.api_tests.support import (
    _UNIT_VALID_SESSION_ID,
    is_capability_unavailable_body,
)

# (path, http method, expected capability status). WS is handled separately.
_BLOCKED_OR_SCAFFOLDED = [
    ("/sessions/{id}/markers", "post", "blocked"),
    ("/sessions/{id}/capture:start", "post", "blocked"),
    ("/sessions/{id}/capture:stop", "post", "blocked"),
    ("/sessions/{id}/close", "post", "blocked"),
    ("/sessions/{id}/arc:run", "post", "blocked"),
]


def _path(template: str) -> str:
    return template.replace("{id}", _UNIT_VALID_SESSION_ID)


@pytest.fixture
def no_db(monkeypatch):
    """Make EVERY DB entry point the api could reach raise; record attempts.

    B3 fix: patching only `psycopg2.connect` leaves a gap — the api reaches the
    DB through its own factories (`api.deps.get_readonly_connection`, and any
    `api.deps.get_connection`). A gated endpoint that called a factory which was
    itself mocked elsewhere would slip past a connect-only guard. We patch the
    driver AND every api factory to raise, then assert the 409 capability body
    still returns with NO DB access.
    """
    calls = []

    def _boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("INV-013/PRH-007: a capability endpoint opened a DB connection")

    # Driver-level guard.
    monkeypatch.setattr("psycopg2.connect", _boom)

    # Every api-level connection factory the route could call through. Patch on
    # the api.deps module so it fires regardless of import style at the call site.
    import api.deps as deps

    for factory in ("get_readonly_connection", "get_connection"):
        if hasattr(deps, factory):
            monkeypatch.setattr(deps, factory, _boom)
    return calls


@pytest.mark.parametrize("template,method,expected_status", _BLOCKED_OR_SCAFFOLDED)
def test_blocked_scaffolded_returns_409_capability_body(
    client, no_db, template, method, expected_status
):
    # Tests INV-013 [integration]: 409 + structured capability-status body.
    resp = getattr(client, method)(_path(template))
    assert resp.status_code == 409, (
        f"{method.upper()} {template} must return 409 capability-status, got {resp.status_code}"
    )
    body = resp.json()
    assert is_capability_unavailable_body(body), f"bad capability body: {body}"
    assert body["status"] in ("blocked", "scaffolded")
    assert body["status"] == expected_status
    assert body["blocked_reason"], "blocked_reason must be a non-empty actionable string"
    assert body["gate"], "gate must name the OQ/gate"


@pytest.mark.parametrize("template,method,expected_status", _BLOCKED_OR_SCAFFOLDED)
def test_blocked_scaffolded_opens_no_db_connection(
    client, no_db, template, method, expected_status
):
    # Tests PRH-007 [integration]: no DB connection opened en route to refusing.
    getattr(client, method)(_path(template))
    assert no_db == [], "INV-013/PRH-007: no DB connection may be opened by a gated endpoint"


def test_arc_run_does_not_enter_run_arc_post_session(client, no_db, monkeypatch):
    # Tests INV-013/PRH-007 [integration]: arc:run must NOT call run_arc_post_session.
    import batch.arc.processor as processor

    called = []
    monkeypatch.setattr(processor, "run_arc_post_session", lambda *a, **k: called.append((a, k)))
    resp = client.post(_path("/sessions/{id}/arc:run"))
    assert resp.status_code == 409
    assert called == [], "arc:run must not invoke run_arc_post_session in M0"


def test_capture_start_does_not_construct_forwarder_engine(client, no_db, monkeypatch):
    # Tests INV-013/PRH-007 [integration]: capture:start must NOT build ForwarderEngine.
    import capture.forwarder.runtime as runtime

    built = []
    orig = runtime.ForwarderEngine

    class _Spy(orig):  # type: ignore[misc, valid-type]
        def __init__(self, *a, **k):
            built.append((a, k))
            raise AssertionError("ForwarderEngine must not be constructed in M0")

    monkeypatch.setattr(runtime, "ForwarderEngine", _Spy)
    resp = client.post(_path("/sessions/{id}/capture:start"))
    assert resp.status_code == 409
    assert built == [], "capture:start must not construct ForwarderEngine in M0"


def test_close_does_not_call_session_close_run(client, no_db, monkeypatch):
    # Tests INV-013/PRH-007 [integration]: close must NOT call session_close.workflow.run.
    import capture.session_close.workflow as close_wf

    called = []
    monkeypatch.setattr(close_wf, "run", lambda *a, **k: called.append((a, k)) or 0)
    resp = client.post(_path("/sessions/{id}/close"))
    assert resp.status_code == 409
    assert called == [], "close must not call session_close.workflow.run in M0"


def test_capability_body_returned_before_validation(client, no_db):
    # Tests INV-013 [integration]: 409 is returned FIRST — even a malformed UUID
    # path must yield the capability body, not a 422 (no validation runs first).
    resp = client.post("/sessions/not-a-uuid/arc:run")
    assert resp.status_code == 409, (
        "capability-status must precede input validation (INV-013 'unconditionally and first')"
    )
    assert is_capability_unavailable_body(resp.json())


def test_scaffolded_ws_refuses_upgrade_with_capability_reason(client):
    # Tests INV-013 / INV-008a [integration]: the scaffolded WS refuses the
    # upgrade with a capability-status close code + reason carrying the
    # capability/status/blocked_reason/gate — NOT a bare default 1000 close.
    from starlette.websockets import WebSocketDisconnect

    path = _path("/sessions/{id}/stream")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(path) as ws:
            # A plain accepted stream is a failure: the upgrade must be refused.
            ws.receive_text()

    code = exc_info.value.code
    reason = str(exc_info.value.reason or "")
    # A refused-with-reason close must use a non-default policy/app close code
    # and surface the capability reason, not the default normal-closure (1000)
    # with an empty reason that the stub emits.
    assert code != 1000, (
        f"WS must refuse with a capability-status close code, not default 1000 (got {code})"
    )
    assert reason, "WS close must carry a capability-status reason string"

    # B5 fix: the close reason must carry the STRUCTURED capability identity, the
    # same four fields the HTTP 409 body carries (capability/status/blocked_reason/
    # gate) — not a loose substring like "oq". Mirror is_capability_unavailable_body.
    # Accept either a JSON reason object or a reason string carrying all four
    # field tokens (close-frame reasons are length-limited, so a token form is OK).
    parsed = None
    try:
        parsed = json.loads(reason)
    except (ValueError, TypeError):
        parsed = None

    if isinstance(parsed, dict):
        assert is_capability_unavailable_body(parsed), (
            f"WS JSON close reason must be the capability-status body, got {parsed!r}"
        )
        assert parsed["status"] in ("blocked", "scaffolded")
    else:
        low = reason.lower()
        for token in ("capability", "status", "blocked_reason", "gate"):
            assert token in low, (
                f"WS close reason must carry the structured capability field "
                f"{token!r} (capability/status/blocked_reason/gate), got {reason!r}"
            )
