from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import db
from .llm import chat_completion, estimate_tokens
from .rag import ingest_paths, retrieve_similar_chunks
from .settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db.init_databases(get_settings())
    yield


app = FastAPI(title="Cloop LLM Service", version="0.1.0", lifespan=lifespan)


def get_app_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


class ChatMessage(BaseModel):
    role: str
    content: str


class ToolCall(BaseModel):
    name: str = Field(..., description="Supported: read_note, write_note")
    note_id: Optional[int] = None
    title: Optional[str] = None
    body: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    tool_call: Optional[ToolCall] = Field(
        default=None, description="Optional instruction to interact with notes"
    )


class ChatResponse(BaseModel):
    message: str
    tool_result: Optional[Dict[str, Any]] = None


class IngestRequest(BaseModel):
    paths: List[str]


class IngestResponse(BaseModel):
    files: int
    chunks: int


class AskResponse(BaseModel):
    answer: str
    chunks: List[Dict[str, Any]]


def handle_tool_call(tool_call: ToolCall) -> Dict[str, Any]:
    if tool_call.name == "read_note":
        if tool_call.note_id is None:
            raise HTTPException(status_code=400, detail="note_id required for read_note")
        note = db.read_note(tool_call.note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"action": "read_note", "note": note}
    if tool_call.name == "write_note":
        if not tool_call.title or not tool_call.body:
            raise HTTPException(status_code=400, detail="title and body required for write_note")
        note = db.upsert_note(title=tool_call.title, body=tool_call.body, note_id=tool_call.note_id)
        return {"action": "write_note", "note": note}
    raise HTTPException(status_code=400, detail="Unsupported tool name")


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    settings: SettingsDep,
) -> ChatResponse:
    messages = [message.model_dump() for message in request.messages]
    tool_result: Optional[Dict[str, Any]] = None

    if request.tool_call:
        tool_result = handle_tool_call(request.tool_call)
        messages.append(
            {
                "role": "system",
                "content": f"Tool output: {json.dumps(tool_result)}",
            }
        )

    if not messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    token_estimate = estimate_tokens(messages)
    content, metadata = chat_completion(messages, settings=settings)

    response_payload = {"message": content, "tool_result": tool_result, "metadata": metadata}
    db.record_interaction(
        endpoint="/chat",
        request_payload=request.model_dump(),
        response_payload=response_payload,
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        token_estimate=token_estimate,
        settings=settings,
    )

    return ChatResponse(message=content, tool_result=tool_result)


@app.post("/ingest", response_model=IngestResponse)
def ingest_endpoint(
    request: IngestRequest,
    settings: SettingsDep,
) -> IngestResponse:
    if not request.paths:
        raise HTTPException(status_code=400, detail="paths cannot be empty")
    result = ingest_paths(request.paths, settings=settings)
    db.record_interaction(
        endpoint="/ingest",
        request_payload=request.model_dump(),
        response_payload=result,
        model=settings.embed_model,
        latency_ms=None,
        token_estimate=None,
        settings=settings,
    )
    return IngestResponse(**result)


@app.get("/ask", response_model=AskResponse)
def ask_endpoint(
    settings: SettingsDep,
    q: str = Query(..., description="Question to run against the knowledge base"),
    k: Optional[int] = Query(None, description="Override number of chunks to return"),
) -> AskResponse:
    top_k = k or settings.default_top_k
    if top_k <= 0:
        raise HTTPException(status_code=400, detail="k must be positive")

    chunks = retrieve_similar_chunks(q, top_k=top_k, settings=settings)
    if not chunks:
        return AskResponse(answer="No knowledge available. Ingest documents first.", chunks=[])

    context = "\n\n".join(
        f"[{idx}] {chunk['content']}" for idx, chunk in enumerate(chunks, start=1)
    )
    messages = [
        {
            "role": "system",
            "content": "Use the provided context to answer. If unsure, say you do not know.",
        },
        {
            "role": "user",
            "content": f"Question: {q}\n\nContext:\n{context}",
        },
    ]
    token_estimate = estimate_tokens(messages)
    content, metadata = chat_completion(messages, settings=settings)

    db.record_interaction(
        endpoint="/ask",
        request_payload={"q": q, "k": top_k},
        response_payload={"answer": content},
        model=metadata.get("model"),
        latency_ms=metadata.get("latency_ms"),
        token_estimate=token_estimate,
        selected_chunks=chunks,
        settings=settings,
    )

    return AskResponse(answer=content, chunks=chunks)
