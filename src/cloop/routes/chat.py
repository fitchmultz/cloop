"""Chat completion endpoint with optional tool support.

Supports:
- Basic chat completions
- Manual tool execution (read_note, write_note)
- LLM-orchestrated tool mode
- SSE streaming for real-time responses
"""

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import db
from ..llm import (
    ToolCallError,
    chat_completion,
    chat_with_tools,
    estimate_tokens,
    stream_completion,
)
from ..loops.errors import CloopError
from ..schemas.chat import ChatRequest, ChatResponse, _InteractionMetadata
from ..settings import Settings, ToolMode, get_settings
from ..tools import EXECUTORS, TOOL_SPECS

router = APIRouter(prefix="/chat", tags=["chat"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


def handle_tool_call(tool_call, settings: Settings) -> Dict[str, Any]:
    """Execute a manual tool call."""
    executor = EXECUTORS.get(tool_call.name)
    if executor is None:
        raise HTTPException(status_code=400, detail="Unsupported tool name")
    payload = tool_call.model_dump(exclude_none=True, exclude={"name"})
    try:
        return executor(**payload)
    except CloopError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _sse_event(event: str, payload: Dict[str, Any]) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _interaction_context(settings: Settings) -> Dict[str, str]:
    """Build interaction context for logging."""
    backend = db.get_vector_backend()
    return {
        "embed_model": settings.embed_model,
        "vector_search_mode": settings.vector_search_mode.value,
        "embed_storage_mode": settings.embed_storage_mode.value,
        "vector_backend": backend.value,
    }


@router.post("", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
    stream: Annotated[bool | None, Query(description="Stream Server-Sent Events when true")] = None,
) -> Any:
    messages = [message.model_dump() for message in request.messages]
    tool_result: Dict[str, Any] | None = None
    tool_calls: List[Dict[str, Any]] = []

    tool_mode = request.tool_mode or settings.tool_mode_default

    if request.tool_call and tool_mode is not ToolMode.MANUAL:
        raise HTTPException(status_code=400, detail="tool_call is only supported in manual mode")

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

    token_estimate = estimate_tokens(messages)
    stream_enabled = stream if stream is not None else settings.stream_default
    if stream_enabled and tool_mode is ToolMode.LLM:
        raise HTTPException(status_code=400, detail="Streaming not supported for llm tool_mode")

    context_snapshot = _interaction_context(settings)

    if stream_enabled:
        request_payload = request.model_dump()
        request_payload["stream"] = True

        def event_stream() -> Iterator[str]:
            start = time.monotonic()
            tokens: List[str] = []
            for token in stream_completion(messages, settings=settings):
                if not token:
                    continue
                tokens.append(token)
                yield _sse_event("token", {"token": token})
            final_message = "".join(tokens)
            metadata: _InteractionMetadata = {
                "model": settings.llm_model,
                "latency_ms": (time.monotonic() - start) * 1000,
                "usage": {},
            }
            response_payload = {
                "message": final_message,
                "tool_result": tool_result,
                "metadata": metadata,
                "tool_calls": tool_calls,
                "context": context_snapshot,
            }
            db.record_interaction(
                endpoint="/chat",
                request_payload=request_payload,
                response_payload=response_payload,
                model=metadata["model"],
                latency_ms=metadata["latency_ms"],
                token_estimate=token_estimate,
                tool_calls=tool_calls,
                settings=settings,
            )
            yield _sse_event(
                "done",
                {
                    "message": final_message,
                    "model": metadata["model"],
                    "tool_result": tool_result,
                    "tool_calls": tool_calls,
                },
            )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    if tool_mode is ToolMode.LLM:
        try:
            content, metadata, tool_calls = chat_with_tools(messages, TOOL_SPECS, settings=settings)
        except ToolCallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        outputs = metadata.get("tool_outputs") or []
        tool_result = outputs[0] if outputs else None
    else:
        content, metadata = chat_completion(messages, settings=settings)

    response_payload = {
        "message": content,
        "tool_result": tool_result,
        "metadata": metadata,
        "tool_calls": tool_calls,
        "context": context_snapshot,
    }
    db.record_interaction(
        endpoint="/chat",
        request_payload=request.model_dump(),
        response_payload=response_payload,
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        token_estimate=token_estimate,
        tool_calls=tool_calls,
        settings=settings,
    )

    return ChatResponse(
        message=content,
        tool_result=tool_result,
        tool_calls=tool_calls,
        model=metadata.get("model"),
    )
