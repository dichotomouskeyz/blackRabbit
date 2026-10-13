"""RI-008/012: native provider wire adapters against isolated mock transports."""

import json

import pytest

pytest.importorskip("pydantic_ai")

import httpx2  # noqa: E402
from pydantic_ai import models  # noqa: E402
from pydantic_ai.models.anthropic import AnthropicModel  # noqa: E402
from pydantic_ai.models.openai import OpenAIResponsesModel  # noqa: E402
from pydantic_ai.providers.anthropic import AnthropicProvider  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402

from investigation.models import Evidence  # noqa: E402
from investigation.runtime import run_investigation  # noqa: E402


class MarkerTools:
    session_id = "test-session"
    analysis_id = "test-analysis"
    artifact_sha256 = "immutable-hash"

    def __init__(self):
        self.evidence = {}
        self.charts = []
        self.trace = []

    def list_events(self, label=None):
        self.trace.append({"tool": "list_events"})
        self.evidence["marker-evidence"] = Evidence(
            id="marker-evidence",
            session_id=self.session_id,
            analysis_id=self.analysis_id,
            artifact_sha256=self.artifact_sha256,
            source="session_metadata",
            metric="marker_count",
            value=1,
        )
        return {"events": [{"event_id": 42}], "evidence_ids": ["marker-evidence"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_provider_wire_roundtrip_executes_tool_and_validates_cited_output(provider):
    from anthropic import AsyncAnthropic
    from openai import AsyncOpenAI

    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        tool_definitions = body["tools"]
        output_name = next(
            item["name"] for item in tool_definitions if item["name"] == "final_result"
        )
        name = "list_events" if len(calls) == 1 else output_name
        arguments = (
            {}
            if len(calls) == 1
            else {
                "summary": "The recording has one marker.",
                "findings": [
                    {"text": "One marker was recorded.", "evidence_ids": ["marker-evidence"]}
                ],
            }
        )
        if provider == "openai":
            response = {
                "id": f"resp_{len(calls)}",
                "object": "response",
                "created_at": 123,
                "status": "completed",
                "model": "gpt-4.1-mini",
                "output": [
                    {
                        "type": "function_call",
                        "id": f"fc_{len(calls)}",
                        "call_id": f"call_{len(calls)}",
                        "name": name,
                        "arguments": json.dumps(arguments),
                        "status": "completed",
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 20, "total_tokens": 40},
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": tool_definitions,
            }
        else:
            response = {
                "id": f"msg_{len(calls)}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"call_{len(calls)}",
                        "name": name,
                        "input": arguments,
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 20},
            }
        return httpx2.Response(200, json=response)

    # The only permitted provider calls in this test have an in-process
    # MockTransport. No DNS, socket, credentials or real provider is involved.
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        if provider == "openai":
            native = AsyncOpenAI(api_key="offline-fixture", max_retries=1, http_client=client)
            model = OpenAIResponsesModel(
                "gpt-4.1-mini", provider=OpenAIProvider(openai_client=native)
            )
        else:
            native = AsyncAnthropic(api_key="offline-fixture", max_retries=1, http_client=client)
            model = AnthropicModel(
                "claude-sonnet-4-6", provider=AnthropicProvider(anthropic_client=native)
            )
        tools = MarkerTools()
        with models.override_allow_model_requests(True):
            result = await run_investigation("Locate the marker.", tools, model=model)
    assert len(calls) == 2
    assert tools.trace == [{"tool": "list_events"}]
    assert result.report.evidence[0].value == 1
    assert result.report.analysis_id == "test-analysis"
    # The second provider request carries the server tool result through the
    # actual native adapter, not a fabricated model-only history.
    assert "marker-evidence" in json.dumps(calls[1])
    assert models.ALLOW_MODEL_REQUESTS is False
