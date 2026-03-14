"""Chat completion endpoint with grounded-context controls and optional tool support.

Purpose:
    HTTP endpoint for chat completions over the shared pi-backed runtime.

Responsibilities:
    - POST /chat: chat completion endpoint
    - Transport formatting for the shared chat execution flow
    - Stable HTTP error mapping for chat and tool execution failures

Non-scope:
    - LLM provider logic (see llm.py)
    - Shared chat execution/orchestration (see chat_execution.py)
    - Tool implementations (see tools.py)
"""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..chat_execution import execute_chat_request, stream_chat_request
from ..loops.errors import CloopError
from ..schemas.chat import ChatRequest, ChatResponse
from ..settings import Settings, get_settings
from ..sse import format_sse_event

router = APIRouter(prefix="/chat", tags=["chat"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


@router.post("", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
    stream: Annotated[bool | None, Query(description="Stream Server-Sent Events when true")] = None,
) -> Any:
    stream_enabled = stream if stream is not None else settings.stream_default

    if stream_enabled:

        def event_stream() -> Iterator[str]:
            try:
                for event in stream_chat_request(
                    request=request,
                    settings=settings,
                    endpoint="/chat",
                ):
                    if event.type == "text_delta":
                        yield format_sse_event("token", event.payload)
                    elif event.type == "tool_call":
                        yield format_sse_event("tool_call", event.payload)
                    elif event.type == "tool_result":
                        yield format_sse_event("tool_result", event.payload)
                    elif event.type == "done":
                        yield format_sse_event("done", event.payload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except CloopError:
                raise

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    try:
        result = execute_chat_request(request=request, settings=settings, endpoint="/chat")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CloopError:
        raise

    return result.response
