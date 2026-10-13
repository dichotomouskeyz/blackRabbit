"""Scripted offline FunctionModel, exercising real tools without model claims."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel


def _responses(messages: list[ModelMessage]) -> dict[str, Any]:
    returned: dict[str, Any] = {}
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                returned.clear()
            elif isinstance(part, ToolReturnPart) and part.outcome == "success":
                returned[part.tool_name] = part.content
    return returned


def _refs(payload: dict, metrics: list[str], **scope: Any) -> list[str]:
    return [
        ref
        for ref, metadata in payload.get("evidence_refs", {}).items()
        if metadata["metric"] in metrics
        and all(metadata.get(key) == value for key, value in scope.items())
    ]


def _format(value: Any) -> str:
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def _findings(results: dict) -> list[dict]:
    findings: list[dict] = []

    def add(text: str, refs: list[str]) -> None:
        if refs:
            findings.append({"text": text, "evidence_ids": refs[:30]})

    quality = results["get_recording_quality"]
    for modality, values in quality.get("quality_summary", {}).items():
        counts = {key: value for key, value in values.items() if key.endswith("count")}
        add(
            f"Saved {modality} quality: "
            + "; ".join(f"{key}={_format(value)}" for key, value in counts.items())
            + ".",
            _refs(quality, list(counts), modality=modality),
        )

    window = results.get("inspect_signal_window", {})
    for channel, statistics in window.get("statistics", {}).items():
        if not isinstance(statistics, dict):
            continue
        selected = {
            key: statistics[key] for key in ("mean", "std", "sample_count") if key in statistics
        }
        add(
            f"Exploratory {channel} window: "
            + "; ".join(f"{key}={_format(value)}" for key, value in selected.items())
            + ". These descriptive values do not establish new significance.",
            _refs(window, [f"{channel}.{key}" for key in selected]),
        )

    saved = results.get("get_event_response", {})
    response = saved.get("response", {})
    selected = {
        key: response[key]
        for key in ("p_value", "fdr_q_value", "passed_fdr", "testable")
        if key in response
    }
    add(
        "Saved event test: "
        + "; ".join(f"{key}={_format(value)}" for key, value in selected.items())
        + ".",
        _refs(saved, list(selected), window=None),
    )
    for name, saved_window in sorted(response.get("windows", {}).items())[:1]:
        metrics = saved_window.get("metrics", {})
        # Demonstrate three actual signal changes without manufacturing narrative.
        selected_metrics = sorted(
            metrics.items(), key=lambda item: (not item[1].get("participates", False), item[0])
        )[:3]
        for component, values in selected_metrics:
            keys = ["observed_value", "baseline_mean", "deviation", "units"]
            add(
                f"Saved {name} {component}: "
                f"observed={_format(values.get('observed_value'))} "
                f"{values.get('units', '')}; baseline={_format(values.get('baseline_mean'))}; "
                f"standardized deviation={_format(values.get('deviation'))}.",
                _refs(saved, [f"{component}.{key}" for key in keys], window=name),
            )
    if not findings:
        # Minimal fixture datasets can still demonstrate canonical evidence hydration.
        for name in ("get_recording_quality", "inspect_signal_window", "get_event_response"):
            refs = results.get(name, {}).get("evidence_ids", [])
            add(f"Retrieved {name} evidence for the selected recording.", refs[:20])
    return findings[:20]


def _limitations(results: dict) -> list[str]:
    quality = results["get_recording_quality"]
    limitations = [str(item) for item in quality.get("limitations", [])][:12]
    limitations.extend(results.get("inspect_signal_window", {}).get("limitations", [])[:2])
    for modality, reason in quality.get("unavailable_signals", {}).items():
        limitations.append(f"Unavailable {modality}: {reason}")
    for event in quality.get("event_exclusions", []):
        if event.get("test_exclusion_reason"):
            limitations.append(f"Event {event['event_id']}: {event['test_exclusion_reason']}")
        for name, window in event.get("windows", {}).items():
            if window.get("exclusion_reason"):
                limitations.append(
                    f"Event {event['event_id']} {name}: {window['exclusion_reason']}"
                )
            for component, reason in window.get("excluded_signals", {}).items():
                limitations.append(f"Event {event['event_id']} {name} {component}: {reason}")
    return limitations[:19] + [
        "This fixed sequence demonstrates tool execution and measured evidence, "
        "not live model interpretation."
    ]


def _call(messages: list[ModelMessage], info: AgentInfo) -> ToolCallPart:
    results = _responses(messages)
    for name in ("get_session_summary", "list_events", "get_recording_quality"):
        if name not in results:
            return ToolCallPart(name, {})
    events = results["list_events"].get("events", [])
    event = next((item for item in events if item.get("has_saved_response")), None)
    if event is not None:
        if "inspect_signal_window" not in results:
            timestamp = float(event["lsl_timestamp"])
            channels = results["get_session_summary"].get("channels", [])
            channel = next((item for item in channels if item["modality"] == "eda"), None)
            modality = channel["modality"] if channel else "hrv"
            return ToolCallPart(
                "inspect_signal_window",
                {
                    "modality": modality,
                    "start_lsl_timestamp": max(0, timestamp - 10),
                    "end_lsl_timestamp": timestamp + 10,
                },
            )
        if "get_event_response" not in results:
            return ToolCallPart("get_event_response", {"event_id": event["event_id"]})

    draft = {
        "summary": "Scripted synthetic demonstration. No live model was used.",
        "findings": _findings(results),
        "quality_limitations": _limitations(results),
        "unresolved_questions": [] if event is not None else ["No event has a saved ARC response."],
    }
    return ToolCallPart(info.output_tools[0].name, draft)


def build_demo_model() -> FunctionModel:
    """Exercise the SDK loop using tool responses, with no network or API key."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[_call(messages, info)])

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        call = _call(messages, info)
        yield {
            0: DeltaToolCall(
                name=call.tool_name,
                json_args=json.dumps(call.args),
                tool_call_id=call.tool_call_id,
            )
        }

    return FunctionModel(function=respond, stream_function=stream, model_name="scripted-demo")
