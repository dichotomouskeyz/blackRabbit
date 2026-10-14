"""Optional recording investigation endpoint; SDK imports are request-local."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing, suppress
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api import deps
from investigation.conversations import ConversationStore
from investigation.models import InvestigationError, build_report

TURN_TIMEOUT_SECONDS = 90.0


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID
    conversation_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must contain text")
        return value


def _create_agent():
    from investigation.runtime import create_agent

    return create_agent()


def _create_tools(session_id: str, sponsor_id: str, site_id: str):
    from investigation.tools import RecordingTools

    return RecordingTools(
        session_id=session_id,
        sponsor_id=sponsor_id,
        site_id=site_id,
    )


def install(app: FastAPI) -> None:
    store = ConversationStore()
    app.state.investigation_conversations = store

    @app.post("/agent/chat", response_model=None)
    async def chat(
        body: ChatRequest,
        request: Request,
        tenant: deps.TenantContext = Depends(deps.get_tenant_context),
    ):
        validated = deps.require_tenant(tenant)
        conversation = None
        agent = None
        prepared = False
        deadline = asyncio.get_running_loop().time() + TURN_TIMEOUT_SECONDS
        try:
            # The ordinary FastAPI package can load without the optional SDK.
            from pydantic_ai.ui.vercel_ai import VercelAIAdapter
            from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage
            from pydantic_ai.ui.vercel_ai.response_types import DataChunk, ErrorChunk

            from investigation.runtime import AgentDependencies, usage_limits

            agent = _create_agent()
            conversation = store.acquire(
                validated.sponsor_id,
                validated.site_id,
                str(body.session_id),
                str(body.conversation_id) if body.conversation_id else None,
            )
            if conversation.tools is None:
                async with asyncio.timeout_at(deadline):
                    conversation.tools = await asyncio.to_thread(
                        _create_tools,
                        str(body.session_id),
                        validated.sponsor_id,
                        validated.site_id,
                    )
            prepared = True
        except ImportError:
            if conversation:
                store.discard(conversation)
            return JSONResponse(
                status_code=503,
                content={
                    "error": "agent_unavailable",
                    "message": "Install the optional agent extra.",
                },
            )
        except InvestigationError as exc:
            if conversation:
                store.discard(conversation)
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": exc.code, "message": str(exc)},
            )
        except TimeoutError:
            if conversation:
                store.discard(conversation)
            return JSONResponse(
                status_code=503,
                content={"error": "agent_timeout", "message": "Investigation setup timed out."},
            )
        except BaseException:
            if conversation:
                store.discard(conversation)
            raise
        finally:
            if agent is not None and not prepared:
                # Native providers allocate their HTTP client at construction.
                # Even a pre-stream 404/409/503 must release that client.
                async with agent:
                    pass

        run_id = str(uuid4())
        adapter = VercelAIAdapter(
            agent=agent,
            sdk_version=7,
            server_message_id=run_id,
            run_input=SubmitMessage(
                id=conversation.id,
                messages=[
                    UIMessage(
                        id=str(uuid4()),
                        role="user",
                        parts=[TextUIPart(text=body.message)],
                    )
                ],
            ),
        )

        async def stream():
            completed = False
            new_messages = []
            stream_task = asyncio.current_task()

            async def watch_disconnect():
                # Check even while the provider has yielded no events. This
                # also covers ASGI servers using the newer send-error path.
                while True:
                    if await request.is_disconnected():
                        if stream_task is not None:
                            stream_task.cancel()
                        return
                    await asyncio.sleep(0.1)

            disconnect_task = asyncio.create_task(watch_disconnect())

            async def on_complete(result):
                nonlocal completed, new_messages
                report = build_report(result.output, conversation.tools)
                # Adapter passes this turn's user prompt as trusted history, so
                # include it explicitly before the new model/tool messages.
                new_messages = [*adapter.messages, *result.new_messages()]
                completed = True
                yield DataChunk(type="data-investigation", data=report.model_dump(mode="json"))

            native = cast(
                AsyncGenerator[Any, None],
                adapter.run_stream_native(
                    message_history=conversation.history,
                    conversation_id=conversation.id,
                    run_id=run_id,
                    deps=AgentDependencies(conversation.tools),
                    usage_limits=usage_limits(),
                ),
            )
            transformed = cast(
                AsyncGenerator[Any, None], adapter.transform_stream(native, on_complete=on_complete)
            )
            try:
                async with asyncio.timeout_at(deadline), agent:
                    yield DataChunk(
                        type="data-conversation",
                        data={
                            "conversation_id": conversation.id,
                            "run_id": run_id,
                            "session_id": conversation.session_id,
                            "analysis_id": conversation.tools.analysis_id,
                        },
                    )
                    async with aclosing(transformed):
                        async for event in transformed:
                            # SDK errors can contain provider details. Emit a
                            # stable error and retain no failed conversation.
                            if isinstance(event, ErrorChunk):
                                completed = False
                                yield ErrorChunk(
                                    error_text="Investigation failed; start a new conversation."
                                )
                            else:
                                yield event
                            charts = conversation.tools.charts
                            while charts:
                                yield DataChunk(type="data-signal-chart", data=charts.pop(0))
            except TimeoutError:
                completed = False
                yield ErrorChunk(error_text="Investigation timed out; start a new conversation.")
            finally:
                disconnect_task.cancel()
                try:
                    with suppress(asyncio.CancelledError):
                        await disconnect_task
                    await native.aclose()
                finally:
                    if completed:
                        store.finish(conversation, new_messages)
                    else:
                        store.discard(conversation)

        return StreamingResponse(
            adapter.encode_stream(stream()),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "x-vercel-ai-ui-message-stream": "v1"},
        )
