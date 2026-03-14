"""Shared chat execution orchestration.

Purpose:
    Centralize the full chat execution flow so HTTP, CLI, and future transports
    can share one canonical contract for request preparation, tool handling,
    response shaping, streaming, and interaction logging.

Responsibilities:
    - Prepare chat requests via `chat_orchestration`
    - Execute manual tool calls and bridge-backed chat completions
    - Stream transport-neutral chat events
    - Build the canonical `ChatResponse`
    - Persist interaction logs with stable request/response payloads

Non-scope:
    - HTTP/SSE formatting
    - CLI argument parsing or text rendering
    - Bridge subprocess lifecycle management
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .chat_orchestration import PreparedChatRequest, prepare_chat_request
from .llm import ToolCallError, chat_completion, chat_with_tools, stream_events
from .schemas.chat import (
    ChatContextResponse,
    ChatMetadataResponse,
    ChatOptionsResponse,
    ChatRequest,
    ChatResponse,
)
from .settings import Settings, ToolMode
from .storage import interaction_store
from .tools import get_agent_bridge_tools, get_tool_definition


@dataclass(slots=True, frozen=True)
class PreparedChatExecution:
    """Prepared execution state shared by streaming and non-streaming flows."""

    prepared: PreparedChatRequest
    request_payload: dict[str, Any]
    messages: list[dict[str, Any]]
    tool_mode: ToolMode
    tool_result: dict[str, Any] | None
    tool_calls: list[dict[str, Any]]


@dataclass(slots=True, frozen=True)
class StreamedChatEvent:
    """Transport-neutral streamed chat event."""

    type: str
    payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class ChatExecutionResult:
    """Completed chat execution result."""

    response: ChatResponse
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    prepared: PreparedChatRequest
    tool_calls: list[dict[str, Any]]


def execute_manual_tool_call(*, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute one manual chat tool call via the canonical tool registry."""
    tool_definition = get_tool_definition(name)
    if tool_definition is None or not tool_definition.manual_exposed:
        raise ValueError(f"Unsupported tool: {name}")
    return tool_definition.executor(**arguments)


def _coerce_usage_payload(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        dumped = usage.model_dump()
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    if hasattr(usage, "dict"):
        dumped = usage.dict()
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    if hasattr(usage, "__dict__"):
        dumped = usage.__dict__
        return dumped if isinstance(dumped, dict) else {"value": dumped}
    return {"value": str(usage)}


def _metadata_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "latency_ms": float(metadata.get("latency_ms", 0.0)) if metadata else 0.0,
        "model": metadata.get("model") if metadata else None,
        "provider": metadata.get("provider") if metadata else None,
        "api": metadata.get("api") if metadata else None,
        "usage": _coerce_usage_payload(metadata.get("usage")) if metadata else {},
        "stop_reason": metadata.get("stop_reason") if metadata else None,
    }


def _metadata_response(metadata: dict[str, Any]) -> ChatMetadataResponse:
    return ChatMetadataResponse(**_metadata_payload(metadata))


def _options_payload(prepared: PreparedChatRequest) -> dict[str, Any]:
    return {
        "tool_mode": prepared.effective_options.tool_mode,
        "include_loop_context": prepared.effective_options.include_loop_context,
        "include_memory_context": prepared.effective_options.include_memory_context,
        "memory_limit": prepared.effective_options.memory_limit,
        "include_rag_context": prepared.effective_options.include_rag_context,
        "rag_k": prepared.effective_options.rag_k,
        "rag_scope": prepared.effective_options.rag_scope,
    }


def _options_response(prepared: PreparedChatRequest) -> ChatOptionsResponse:
    return ChatOptionsResponse(**_options_payload(prepared))


def _context_response(prepared: PreparedChatRequest) -> ChatContextResponse:
    return ChatContextResponse(**prepared.context_summary)


def _response_payload(
    *,
    prepared: PreparedChatRequest,
    message: str,
    tool_result: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "message": message,
        "tool_result": tool_result,
        "metadata": _metadata_payload(metadata),
        "tool_calls": tool_calls,
        "context": prepared.interaction_context,
        "context_summary": prepared.context_summary,
        "options": _options_payload(prepared),
        "sources": prepared.sources,
    }


def _chat_response(
    *,
    prepared: PreparedChatRequest,
    message: str,
    tool_result: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> ChatResponse:
    metadata_response = _metadata_response(metadata)
    return ChatResponse(
        message=message,
        tool_result=tool_result,
        tool_calls=tool_calls,
        model=metadata_response.model,
        metadata=metadata_response,
        options=_options_response(prepared),
        context=_context_response(prepared),
        sources=prepared.sources,
    )


def _prepare_execution(*, request: ChatRequest, settings: Settings) -> PreparedChatExecution:
    prepared = prepare_chat_request(request=request, settings=settings)
    tool_mode = prepared.effective_options.tool_mode
    tool_result: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = []

    if request.tool_call and tool_mode is not ToolMode.MANUAL:
        raise ValueError("tool_call is only supported in manual mode")

    messages = list(prepared.messages)
    if tool_mode is ToolMode.MANUAL:
        tool_call = request.tool_call
        if tool_call is None:
            raise ValueError("tool_call required in manual mode")
        tool_result = execute_manual_tool_call(name=tool_call.name, arguments=tool_call.arguments)
        messages.append(
            {
                "role": "system",
                "content": f"Tool output: {json.dumps(tool_result)}",
            }
        )

    request_payload = request.model_dump(mode="json")
    request_payload["effective_options"] = {
        **_options_payload(prepared),
        "tool_mode": prepared.effective_options.tool_mode.value,
    }

    return PreparedChatExecution(
        prepared=prepared,
        request_payload=request_payload,
        messages=messages,
        tool_mode=tool_mode,
        tool_result=tool_result,
        tool_calls=tool_calls,
    )


def _record_chat_interaction(
    *,
    endpoint: str,
    execution: PreparedChatExecution,
    response_payload: dict[str, Any],
    metadata: dict[str, Any],
    settings: Settings,
) -> None:
    interaction_store.record_interaction(
        endpoint=endpoint,
        request_payload=execution.request_payload,
        response_payload=response_payload,
        model=response_payload["metadata"]["model"],
        latency_ms=response_payload["metadata"]["latency_ms"],
        token_estimate=execution.prepared.token_estimate,
        selected_chunks=execution.prepared.rag_chunks,
        tool_calls=execution.tool_calls,
        settings=settings,
    )


def execute_chat_request(
    *,
    request: ChatRequest,
    settings: Settings,
    endpoint: str = "/chat",
) -> ChatExecutionResult:
    """Run the canonical non-streaming chat execution flow."""
    execution = _prepare_execution(request=request, settings=settings)
    tool_result = execution.tool_result
    tool_calls = execution.tool_calls

    if execution.tool_mode is ToolMode.LLM:
        try:
            content, metadata, tool_calls = chat_with_tools(
                execution.messages,
                get_agent_bridge_tools(),
                settings=settings,
            )
        except ToolCallError as exc:
            raise ValueError(str(exc)) from exc
        outputs = metadata.get("tool_outputs") or []
        if outputs:
            first_output = outputs[0]
            tool_result = (
                first_output.get("output") if isinstance(first_output, dict) else first_output
            )
    else:
        content, metadata = chat_completion(execution.messages, settings=settings)

    response_payload = _response_payload(
        prepared=execution.prepared,
        message=content,
        tool_result=tool_result,
        tool_calls=tool_calls,
        metadata=metadata,
    )
    _record_chat_interaction(
        endpoint=endpoint,
        execution=PreparedChatExecution(
            prepared=execution.prepared,
            request_payload=execution.request_payload,
            messages=execution.messages,
            tool_mode=execution.tool_mode,
            tool_result=tool_result,
            tool_calls=tool_calls,
        ),
        response_payload=response_payload,
        metadata=metadata,
        settings=settings,
    )

    response = _chat_response(
        prepared=execution.prepared,
        message=content,
        tool_result=tool_result,
        tool_calls=tool_calls,
        metadata=metadata,
    )
    return ChatExecutionResult(
        response=response,
        request_payload=execution.request_payload,
        response_payload=response_payload,
        prepared=execution.prepared,
        tool_calls=tool_calls,
    )


def _stream_prepared_chat_request(
    *,
    execution: PreparedChatExecution,
    settings: Settings,
    endpoint: str,
) -> Iterator[StreamedChatEvent]:
    tool_calls = execution.tool_calls
    tool_result = execution.tool_result
    metadata: dict[str, Any] = {
        "model": settings.pi_model,
        "latency_ms": 0.0,
        "usage": {},
        "provider": None,
        "api": None,
        "stop_reason": None,
    }
    tokens: list[str] = []

    active_tools = get_agent_bridge_tools() if execution.tool_mode is ToolMode.LLM else None
    for event in stream_events(
        execution.messages,
        settings=settings,
        tools=active_tools,
        max_tool_rounds=settings.pi_max_tool_rounds,
    ):
        event_type = event["type"]
        if event_type == "text_delta":
            token = str(event.get("delta", ""))
            if not token:
                continue
            tokens.append(token)
            yield StreamedChatEvent(type="text_delta", payload={"token": token})
        elif event_type == "tool_call":
            payload = {
                "tool_call_id": event.get("tool_call_id"),
                "name": event.get("name"),
                "arguments": event.get("arguments") or {},
            }
            tool_calls.append(
                {
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                }
            )
            yield StreamedChatEvent(type="tool_call", payload=payload)
        elif event_type == "tool_result":
            output = event.get("output")
            if isinstance(output, dict) and tool_result is None:
                tool_result = output
            yield StreamedChatEvent(
                type="tool_result",
                payload={
                    "tool_call_id": event.get("tool_call_id"),
                    "name": event.get("name"),
                    "output": output,
                    "is_error": bool(event.get("is_error", False)),
                },
            )
        elif event_type == "done":
            metadata = {
                "model": event.get("model") or settings.pi_model,
                "latency_ms": float(event.get("latency_ms", 0.0)),
                "usage": _coerce_usage_payload(event.get("usage")),
                "provider": event.get("provider"),
                "api": event.get("api"),
                "stop_reason": event.get("stop_reason"),
            }

    final_message = "".join(tokens)
    response_payload = _response_payload(
        prepared=execution.prepared,
        message=final_message,
        tool_result=tool_result,
        tool_calls=tool_calls,
        metadata=metadata,
    )
    _record_chat_interaction(
        endpoint=endpoint,
        execution=PreparedChatExecution(
            prepared=execution.prepared,
            request_payload={**execution.request_payload, "stream": True},
            messages=execution.messages,
            tool_mode=execution.tool_mode,
            tool_result=tool_result,
            tool_calls=tool_calls,
        ),
        response_payload=response_payload,
        metadata=metadata,
        settings=settings,
    )
    response = _chat_response(
        prepared=execution.prepared,
        message=final_message,
        tool_result=tool_result,
        tool_calls=tool_calls,
        metadata=metadata,
    )
    yield StreamedChatEvent(type="done", payload=response.model_dump(mode="json"))


def stream_chat_request(
    *,
    request: ChatRequest,
    settings: Settings,
    endpoint: str = "/chat",
) -> Iterator[StreamedChatEvent]:
    """Run the canonical streaming chat flow with transport-neutral events."""
    execution = _prepare_execution(request=request, settings=settings)
    return _stream_prepared_chat_request(execution=execution, settings=settings, endpoint=endpoint)
