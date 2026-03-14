"""Chat completion endpoint with grounded-context controls and optional tool support.

Purpose:
    HTTP endpoint for chat completions over the shared pi-backed runtime.

Responsibilities:
    - POST /chat: chat completion endpoint
    - Tool execution integration
    - Grounding via loop, memory, and optional RAG context
    - Stable response semantics for metadata, effective options, and sources

Non-scope:
    - LLM provider logic (see llm.py)
    - Tool implementations (see tools.py)
"""

import json
from collections.abc import Iterator
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..chat_orchestration import PreparedChatRequest, prepare_chat_request
from ..llm import (
    ToolCallError,
    chat_completion,
    chat_with_tools,
    stream_events,
)
from ..loops.errors import CloopError
from ..schemas.chat import (
    ChatContextResponse,
    ChatMetadataResponse,
    ChatOptionsResponse,
    ChatRequest,
    ChatResponse,
)
from ..settings import Settings, ToolMode, get_settings
from ..sse import format_sse_event
from ..storage import interaction_store
from ..tools import get_agent_bridge_tools, get_tool_definition

router = APIRouter(prefix="/chat", tags=["chat"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


def handle_tool_call(tool_call, settings: Settings) -> Dict[str, Any]:
    """Execute a manual tool call."""
    tool_definition = get_tool_definition(tool_call.name)
    if tool_definition is None or not tool_definition.manual_exposed:
        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool_call.name}")
    try:
        return tool_definition.executor(**tool_call.arguments)
    except CloopError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
    stream: Annotated[bool | None, Query(description="Stream Server-Sent Events when true")] = None,
) -> Any:
    prepared = prepare_chat_request(request=request, settings=settings)
    tool_mode = prepared.effective_options.tool_mode
    tool_result: Dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = []

    if request.tool_call and tool_mode is not ToolMode.MANUAL:
        raise HTTPException(status_code=400, detail="tool_call is only supported in manual mode")

    messages = list(prepared.messages)
    if tool_mode is ToolMode.MANUAL:
        tool_call = request.tool_call
        if tool_call is None:
            raise HTTPException(status_code=422, detail="tool_call required in manual mode")
        tool_result = handle_tool_call(tool_call, settings)
        messages.append(
            {
                "role": "system",
                "content": f"Tool output: {json.dumps(tool_result)}",
            }
        )

    stream_enabled = stream if stream is not None else settings.stream_default
    request_payload = request.model_dump()
    request_payload["effective_options"] = {
        **_options_payload(prepared),
        "tool_mode": prepared.effective_options.tool_mode.value,
    }

    if stream_enabled:
        request_payload["stream"] = True
        active_tools = get_agent_bridge_tools() if tool_mode is ToolMode.LLM else None
        streamed_tool_result: list[Dict[str, Any] | None] = [tool_result]

        def event_stream() -> Iterator[str]:
            tokens: list[str] = []
            metadata: dict[str, Any] = {
                "model": settings.pi_model,
                "latency_ms": 0.0,
                "usage": {},
                "provider": None,
                "api": None,
                "stop_reason": None,
            }
            for event in stream_events(
                messages,
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
                    yield format_sse_event("token", {"token": token})
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
                    yield format_sse_event("tool_call", payload)
                elif event_type == "tool_result":
                    output = event.get("output")
                    if isinstance(output, dict) and streamed_tool_result[0] is None:
                        streamed_tool_result[0] = output
                    yield format_sse_event(
                        "tool_result",
                        {
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
                prepared=prepared,
                message=final_message,
                tool_result=streamed_tool_result[0],
                tool_calls=tool_calls,
                metadata=metadata,
            )
            interaction_store.record_interaction(
                endpoint="/chat",
                request_payload=request_payload,
                response_payload=response_payload,
                model=response_payload["metadata"]["model"],
                latency_ms=response_payload["metadata"]["latency_ms"],
                token_estimate=prepared.token_estimate,
                selected_chunks=prepared.rag_chunks,
                tool_calls=tool_calls,
                settings=settings,
            )
            yield format_sse_event(
                "done",
                _chat_response(
                    prepared=prepared,
                    message=final_message,
                    tool_result=streamed_tool_result[0],
                    tool_calls=tool_calls,
                    metadata=metadata,
                ).model_dump(mode="json"),
            )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    if tool_mode is ToolMode.LLM:
        try:
            content, metadata, tool_calls = chat_with_tools(
                messages,
                get_agent_bridge_tools(),
                settings=settings,
            )
        except ToolCallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        outputs = metadata.get("tool_outputs") or []
        if outputs:
            first_output = outputs[0]
            tool_result = (
                first_output.get("output") if isinstance(first_output, dict) else first_output
            )
    else:
        content, metadata = chat_completion(messages, settings=settings)

    response_payload = _response_payload(
        prepared=prepared,
        message=content,
        tool_result=tool_result,
        tool_calls=tool_calls,
        metadata=metadata,
    )
    interaction_store.record_interaction(
        endpoint="/chat",
        request_payload=request_payload,
        response_payload=response_payload,
        model=response_payload["metadata"]["model"],
        latency_ms=response_payload["metadata"]["latency_ms"],
        token_estimate=prepared.token_estimate,
        selected_chunks=prepared.rag_chunks,
        tool_calls=tool_calls,
        settings=settings,
    )

    return _chat_response(
        prepared=prepared,
        message=content,
        tool_result=tool_result,
        tool_calls=tool_calls,
        metadata=metadata,
    )
