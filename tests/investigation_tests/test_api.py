"""RI-008/009/010/012: headless stream, ownership, expiry and cancellation."""

import asyncio
import json
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from api import deps
from api import investigation as endpoint
from api.app import create_app
from investigation.conversations import ConversationStore
from investigation.models import Evidence, InvestigationDraft, InvestigationError

pytest.importorskip("pydantic_ai")

from pydantic_ai import Agent
from pydantic_ai import models as sdk_models
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

SESSION = str(uuid4())
SPONSOR = str(uuid4())
SITE = str(uuid4())


class Tools:
    def __init__(self):
        self.session_id = SESSION
        self.analysis_id = str(uuid4())
        self.artifact_sha256 = "a" * 64
        self.charts = []
        self.evidence = {
            "recorded-metric": Evidence(
                id="recorded-metric",
                session_id=SESSION,
                analysis_id=self.analysis_id,
                artifact_sha256=self.artifact_sha256,
                source="raw_window",
                metric="mean",
                value=2.5,
                modality="eda",
                window="0..30",
            )
        }


@pytest.fixture(autouse=True)
def no_model_network(monkeypatch):
    monkeypatch.setattr(sdk_models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def harness(monkeypatch):
    app = create_app()
    app.dependency_overrides[deps.get_tenant_context] = lambda: deps.TenantContext(SPONSOR, SITE)
    tools = Tools()
    monkeypatch.setattr(endpoint, "_create_tools", lambda *args: tools)

    def install_model(stream_function):
        agent = Agent(
            FunctionModel(stream_function=stream_function), output_type=InvestigationDraft
        )

        @agent.tool_plain
        def inspect_signal_window():
            tools.charts.append({"modality": "eda", "points": [[0, 2.5]]})
            return {"evidence_id": "recorded-metric", "mean": 2.5}

        monkeypatch.setattr(endpoint, "_create_agent", lambda: agent)
        return agent

    return app, tools, install_model


def chunks(response):
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


def output(info):
    return {
        0: DeltaToolCall(
            name=info.output_tools[0].name,
            json_args=json.dumps(
                {
                    "summary": "Recorded EDA mean is 2.5.",
                    "findings": [{"text": "Mean is 2.5.", "evidence_ids": ["recorded-metric"]}],
                    "quality_limitations": ["Exploratory description."],
                    "unresolved_questions": [],
                }
            ),
            tool_call_id=str(uuid4()),
        )
    }


def test_streams_sdk_tools_chart_canonical_report_and_trusted_history(harness):
    app, tools, install_model = harness
    seen_messages = []

    async def scripted(messages, info):
        seen_messages.append(messages)
        if len(seen_messages) == 1:
            yield {0: DeltaToolCall(name="inspect_signal_window", json_args="{}", tool_call_id="x")}
        else:
            yield output(info)

    install_model(scripted)
    with TestClient(app) as client:
        first = client.post(
            "/agent/chat", json={"message": "Inspect this event.", "session_id": SESSION}
        )
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        assert first.headers["x-vercel-ai-ui-message-stream"] == "v1"
        events = chunks(first)
        assert any(item["type"] == "tool-input-available" for item in events)
        assert any(item["type"] == "tool-output-available" for item in events)
        assert any(item["type"] == "data-signal-chart" for item in events)
        report = next(item["data"] for item in events if item["type"] == "data-investigation")
        assert report["evidence"][0]["value"] == 2.5
        assert report["analysis_id"] == tools.analysis_id
        assert tools.charts == []
        conversation = next(item["data"] for item in events if item["type"] == "data-conversation")
        second = client.post(
            "/agent/chat",
            json={
                "message": "Explain that measurement.",
                "session_id": SESSION,
                "conversation_id": conversation["conversation_id"],
            },
        )
        assert second.status_code == 200
        assert any(item["type"] == "data-investigation" for item in chunks(second))
        assert len(seen_messages[-1]) > len(seen_messages[0])
        old_prompts = [
            part.content
            for message in seen_messages[-1]
            for part in message.parts
            if part.part_kind == "user-prompt"
        ]
        assert old_prompts == ["Inspect this event.", "Explain that measurement."]


@pytest.mark.parametrize(
    "extra", ["sponsor_id", "site_id", "messages", "model", "history", "tools"]
)
def test_rejects_client_authority_and_tool_history(harness, extra):
    app, _, _ = harness
    with TestClient(app) as client:
        response = client.post(
            "/agent/chat", json={"message": "Inspect", "session_id": SESSION, extra: []}
        )
    assert response.status_code == 422


@pytest.mark.parametrize("message", ["", "  ", "x" * 4001])
def test_rejects_empty_and_oversized_message(harness, message):
    app, _, _ = harness
    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"message": message, "session_id": SESSION})
    assert response.status_code == 422


def test_optional_setup_unavailable_is_structured_503(harness, monkeypatch):
    app, _, _ = harness

    def missing():
        raise InvestigationError("agent_unconfigured", "Configure an agent model.", 503)

    monkeypatch.setattr(endpoint, "_create_agent", missing)
    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"message": "Inspect", "session_id": SESSION})
    assert response.status_code == 503
    assert response.json()["error"] == "agent_unconfigured"


def test_missing_optional_sdk_is_structured_503(harness, monkeypatch):
    app, _, _ = harness
    monkeypatch.setitem(sys.modules, "pydantic_ai.ui.vercel_ai", None)
    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"message": "Inspect", "session_id": SESSION})
    assert response.status_code == 503
    assert response.json()["error"] == "agent_unavailable"


@pytest.mark.parametrize("status,code", [(404, "session_not_found"), (409, "watermark_unverified")])
def test_recording_failures_are_http_errors_before_stream(harness, monkeypatch, status, code):
    app, _, install_model = harness

    async def scripted(messages, info):
        yield output(info)

    install_model(scripted)

    def unavailable(*args):
        raise InvestigationError(code, "Recording unavailable.", status)

    monkeypatch.setattr(endpoint, "_create_tools", unavailable)
    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"message": "Inspect", "session_id": SESSION})
    assert response.status_code == status
    assert response.json()["error"] == code


def test_pre_stream_recording_failure_closes_agent_resources(harness, monkeypatch):
    app, _, install_model = harness
    exited = []

    async def scripted(messages, info):
        yield output(info)

    install_model(scripted)
    original_exit = Agent.__aexit__

    async def tracked_exit(self, *args):
        exited.append(self)
        return await original_exit(self, *args)

    def unavailable(*args):
        raise InvestigationError("session_not_found", "Recording unavailable.", 404)

    monkeypatch.setattr(Agent, "__aexit__", tracked_exit)
    monkeypatch.setattr(endpoint, "_create_tools", unavailable)
    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"message": "Inspect", "session_id": SESSION})
    assert response.status_code == 404
    assert len(exited) == 1


def test_timeout_emits_no_success_and_invalidates_conversation(harness, monkeypatch):
    app, _, install_model = harness
    monkeypatch.setattr(endpoint, "TURN_TIMEOUT_SECONDS", 0.08)

    async def slow(messages, info):
        await asyncio.sleep(10)
        yield output(info)

    install_model(slow)
    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"message": "Inspect", "session_id": SESSION})
        events = chunks(response)
        assert any(item["type"] == "error" for item in events)
        assert not any(item["type"] == "data-investigation" for item in events)
        conversation = next(item["data"] for item in events if item["type"] == "data-conversation")
        retry = client.post(
            "/agent/chat",
            json={
                "message": "Retry",
                "session_id": SESSION,
                "conversation_id": conversation["conversation_id"],
            },
        )
        assert retry.status_code == 404


def test_provider_errors_are_redacted_and_do_not_complete(harness):
    app, _, install_model = harness

    async def failed(messages, info):
        raise RuntimeError("sensitive provider detail")
        yield output(info)

    install_model(failed)
    with TestClient(app) as client:
        response = client.post("/agent/chat", json={"message": "Inspect", "session_id": SESSION})
    assert "sensitive provider detail" not in response.text
    assert any(item["type"] == "error" for item in chunks(response))
    assert not any(item["type"] == "data-investigation" for item in chunks(response))


def test_overlap_rejected_and_disconnect_cancels_stalled_model(harness):
    app, _, install_model = harness

    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        disconnected = False

        async def slow(messages, info):
            started.set()
            try:
                await asyncio.sleep(10)
                yield output(info)
            finally:
                cancelled.set()

        async def receive():
            if disconnected:
                return {"type": "http.disconnect"}
            await asyncio.sleep(10)

        install_model(slow)
        route = next(route for route in app.routes if getattr(route, "path", None) == "/agent/chat")
        request = Request({"type": "http"}, receive=receive)
        body = endpoint.ChatRequest(message="Inspect", session_id=SESSION)
        response = await route.endpoint(body, request, deps.TenantContext(SPONSOR, SITE))
        pieces = []

        async def consume():
            async for piece in response.body_iterator:
                pieces.append(piece)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=3)
        metadata = json.loads(pieces[0][6:])
        conversation_id = metadata["data"]["conversation_id"]
        overlap = await route.endpoint(
            endpoint.ChatRequest(
                message="Again", session_id=SESSION, conversation_id=conversation_id
            ),
            request,
            deps.TenantContext(SPONSOR, SITE),
        )
        assert overlap.status_code == 409
        assert json.loads(overlap.body)["error"] == "conversation_busy"
        disconnected = True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        assert cancelled.is_set()
        assert "data-investigation" not in "".join(pieces)
        retry = await route.endpoint(
            endpoint.ChatRequest(
                message="Again", session_id=SESSION, conversation_id=conversation_id
            ),
            request,
            deps.TenantContext(SPONSOR, SITE),
        )
        assert retry.status_code == 404

    asyncio.run(scenario())


def test_store_scopes_busy_expiry_capacity_and_whole_turn_retention():
    now = [10.0]
    store = ConversationStore(max_conversations=1, max_messages=5, clock=lambda: now[0])
    item = store.acquire(SPONSOR, SITE, SESSION)
    with pytest.raises(InvestigationError, match="already running"):
        store.acquire(SPONSOR, SITE, SESSION, item.id)
    with pytest.raises(InvestigationError) as wrong_scope:
        store.acquire(SPONSOR, str(uuid4()), SESSION, item.id)
    assert wrong_scope.value.status_code == 404
    with pytest.raises(InvestigationError, match="capacity"):
        store.acquire(SPONSOR, SITE, SESSION)
    store.finish(item, ["user", "call", "result", "final"])
    same = store.acquire(SPONSOR, SITE, SESSION, item.id)
    assert same is item
    store.finish(item, ["new-user", "new-final"])
    assert item.history == ["new-user", "new-final"]
    store.acquire(SPONSOR, SITE, SESSION, item.id)
    store.finish(item, list(range(6)))
    assert item.history == []
    now[0] += 1800
    with pytest.raises(InvestigationError) as expired:
        store.acquire(SPONSOR, SITE, SESSION, item.id)
    assert expired.value.status_code == 404
