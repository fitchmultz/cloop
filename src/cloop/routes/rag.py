"""RAG (Retrieval-Augmented Generation) endpoints.

Purpose:
    HTTP endpoints for document ingestion and question answering.

Responsibilities:
    - POST /ingest: Ingest documents into knowledge base
    - GET /ask: Ask questions against the knowledge base
    - Map HTTP transport concerns onto the shared RAG execution contract
    - Format streaming ask responses as Server-Sent Events

Non-scope:
    - Document loading (see rag/loaders.py)
    - Search algorithms (see rag/search.py)
    - Shared ask/ingest execution semantics (see rag_execution.py)

Endpoints:
- POST /ingest: Ingest documents into knowledge base
- GET /ask: Ask questions against the knowledge base
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..loops.errors import CloopError
from ..rag_execution import execute_ask_request, execute_ingest_request, stream_ask_request
from ..schemas.rag import AskResponse, IngestMode, IngestRequest, IngestResponse
from ..settings import Settings, get_settings
from ..sse import format_sse_event

router = APIRouter(tags=["rag"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


@router.post("/ingest", response_model=IngestResponse)
def ingest_endpoint(
    request: IngestRequest,
    settings: SettingsDep,
) -> IngestResponse:
    mode = (request.mode or IngestMode.ADD).value
    recursive = True if request.recursive is None else bool(request.recursive)
    try:
        result = execute_ingest_request(
            paths=request.paths,
            mode=mode,
            recursive=recursive,
            force_rehash=False,
            settings=settings,
            endpoint="/ingest",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.response


@router.get("/ask", response_model=AskResponse)
def ask_endpoint(
    settings: SettingsDep,
    q: Annotated[str, Query(description="Question to run against the knowledge base")],
    k: Annotated[int | None, Query(description="Override number of chunks to return")] = None,
    stream: Annotated[bool | None, Query(description="Stream Server-Sent Events when true")] = None,
    scope: Annotated[
        str | None,
        Query(description="Restrict retrieval by path substring or doc:ID"),
    ] = None,
) -> Any:
    top_k = settings.default_top_k if k is None else k
    stream_enabled = stream if stream is not None else settings.stream_default

    try:
        if stream_enabled:

            def event_stream() -> Iterator[str]:
                for event in stream_ask_request(
                    question=q,
                    top_k=top_k,
                    scope=scope,
                    settings=settings,
                    endpoint="/ask",
                ):
                    if event.type == "text_delta":
                        yield format_sse_event("token", event.payload)
                    elif event.type == "done":
                        yield format_sse_event("done", event.payload)

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        result = execute_ask_request(
            question=q,
            top_k=top_k,
            scope=scope,
            settings=settings,
            endpoint="/ask",
        )
    except (RuntimeError, ValueError, CloopError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return result.response
