"""Pi-backed chat completion and tool execution.

Purpose:
    Provide the app-facing generative AI facade over the local pi bridge.

Responsibilities:
    - Start bridge-backed chat completions
    - Stream structured events and text deltas
    - Execute Python-owned tools during bridge tool loops
    - Return stable metadata for routes, RAG, and enrichment

Non-scope:
    - Embedding generation (see embeddings.py)
    - SSE formatting/HTTP behavior (see routes/)
    - Node bridge subprocess lifecycle (see ai_bridge/runtime.py)
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Generator, Iterator
from typing import Any

from .ai_bridge import get_bridge_runtime
from .ai_bridge.protocol import BridgeStartRequest, BridgeToolSpec
from .loops.errors import CloopError
from .settings import PiThinkingLevel, Settings, get_settings
from .tools import get_agent_bridge_tools, get_tool_definition, normalize_tool_arguments

Message = dict[str, Any]
LLMEvent = dict[str, Any]


class ToolCallError(ValueError):
    """Raised when bridge-specified tool calls are invalid or unsupported."""


def estimate_tokens(messages: list[Message]) -> int:
    return sum(len((message.get("content") or "").split()) for message in messages)


def _tool_error_payload(exc: Exception) -> dict[str, Any]:
    error_type = "tool_error"
    if isinstance(exc, CloopError):
        error_type = exc.__class__.__name__
    elif isinstance(exc, ValueError):
        error_type = "validation_error"
    return {
        "ok": False,
        "error": {
            "type": error_type,
            "message": str(exc),
        },
    }


def _metadata_from_done(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "latency_ms": float(event.get("latency_ms", 0.0)),
        "model": event.get("model"),
        "provider": event.get("provider"),
        "api": event.get("api"),
        "usage": event.get("usage") or {},
        "stop_reason": event.get("stop_reason"),
    }


def _build_request(
    *,
    messages: list[Message],
    settings: Settings,
    model: str,
    thinking_level: PiThinkingLevel,
    timeout_s: float,
    tools: list[BridgeToolSpec] | None,
    max_tool_rounds: int,
) -> BridgeStartRequest:
    return BridgeStartRequest(
        request_id=uuid.uuid4().hex,
        model=model,
        messages=messages,
        thinking_level=thinking_level.value,
        timeout_ms=max(1, int(timeout_s * 1000)),
        max_tool_rounds=max_tool_rounds,
        tools=tools or [],
    )


def stream_events(
    messages: list[Message],
    *,
    settings: Settings | None = None,
    model: str | None = None,
    thinking_level: PiThinkingLevel | None = None,
    timeout_s: float | None = None,
    tools: list[BridgeToolSpec] | None = None,
    max_tool_rounds: int | None = None,
) -> Iterator[LLMEvent]:
    """Yield bridge-backed structured events for one request."""
    settings = settings or get_settings()
    active_model = model or settings.pi_model
    active_thinking = thinking_level or settings.pi_thinking_level
    active_timeout = timeout_s if timeout_s is not None else settings.pi_timeout
    active_max_tool_rounds = max_tool_rounds or settings.pi_max_tool_rounds

    runtime = get_bridge_runtime(settings)
    request = _build_request(
        messages=messages,
        settings=settings,
        model=active_model,
        thinking_level=active_thinking,
        timeout_s=active_timeout,
        tools=tools,
        max_tool_rounds=active_max_tool_rounds,
    )
    session = runtime.open_session(request)
    start = time.monotonic()
    finished = False

    try:
        for event in session.events():
            event_type = str(event.get("type"))
            if event_type == "tool_call":
                tool_name = str(event.get("name", ""))
                tool_definition = get_tool_definition(tool_name)
                if tool_definition is None or not tool_definition.agent_exposed:
                    raise ToolCallError(f"Unsupported tool: {tool_name}")
                arguments = normalize_tool_arguments(event.get("arguments") or {})
                try:
                    payload = tool_definition.executor(**arguments)
                    is_error = False
                except (CloopError, ValueError) as exc:
                    payload = _tool_error_payload(exc)
                    is_error = True
                tool_result_event = {
                    "type": "tool_result",
                    "tool_call_id": event.get("tool_call_id"),
                    "name": tool_name,
                    "arguments": arguments,
                    "output": payload,
                    "is_error": is_error,
                }
                session.send_tool_result(
                    tool_call_id=str(event.get("tool_call_id", "")),
                    payload=payload,
                    is_error=is_error,
                )
                yield {
                    "type": "tool_call",
                    "tool_call_id": event.get("tool_call_id"),
                    "name": tool_name,
                    "arguments": arguments,
                }
                yield tool_result_event
                continue

            if event_type == "done":
                finished = True
                completed = dict(event)
                completed["latency_ms"] = (time.monotonic() - start) * 1000
                yield completed
                break

            yield dict(event)
    finally:
        if not finished:
            session.abort()
        session.close()


def chat_completion(
    messages: list[Message],
    *,
    settings: Settings | None = None,
    model: str | None = None,
    thinking_level: PiThinkingLevel | None = None,
    timeout_s: float | None = None,
) -> tuple[str, dict[str, Any]]:
    content_parts: list[str] = []
    metadata: dict[str, Any] = {}
    for event in stream_events(
        messages,
        settings=settings,
        model=model,
        thinking_level=thinking_level,
        timeout_s=timeout_s,
    ):
        event_type = event["type"]
        if event_type == "text_delta":
            content_parts.append(str(event.get("delta", "")))
        elif event_type == "done":
            metadata = _metadata_from_done(event)
    return "".join(content_parts), metadata


def stream_completion(
    messages: list[Message],
    *,
    settings: Settings | None = None,
    model: str | None = None,
    thinking_level: PiThinkingLevel | None = None,
    timeout_s: float | None = None,
) -> Generator[str, None, None]:
    for event in stream_events(
        messages,
        settings=settings,
        model=model,
        thinking_level=thinking_level,
        timeout_s=timeout_s,
    ):
        if event["type"] == "text_delta":
            delta = str(event.get("delta", ""))
            if delta:
                yield delta


def chat_with_tools(
    messages: list[Message],
    tools: list[BridgeToolSpec] | None = None,
    *,
    settings: Settings | None = None,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    settings = settings or get_settings()
    content_parts: list[str] = []
    metadata: dict[str, Any] = {}
    tool_calls: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []

    for event in stream_events(
        messages,
        settings=settings,
        tools=tools or get_agent_bridge_tools(),
        max_tool_rounds=settings.pi_max_tool_rounds,
    ):
        event_type = event["type"]
        if event_type == "text_delta":
            content_parts.append(str(event.get("delta", "")))
        elif event_type == "tool_call":
            tool_calls.append(
                {
                    "name": event.get("name"),
                    "arguments": event.get("arguments") or {},
                }
            )
        elif event_type == "tool_result":
            tool_outputs.append(
                {
                    "name": event.get("name"),
                    "output": event.get("output"),
                    "is_error": bool(event.get("is_error", False)),
                }
            )
        elif event_type == "done":
            metadata = _metadata_from_done(event)

    metadata["tool_outputs"] = tool_outputs
    return "".join(content_parts), metadata, tool_calls
