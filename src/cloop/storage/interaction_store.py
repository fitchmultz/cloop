"""Interaction log storage.

Purpose:
    Persist chat and retrieval interaction traces in the core database.

Responsibilities:
    - Sanitize interaction payloads for JSON storage
    - Insert interaction rows into `interactions`

Non-scope:
    - HTTP or chat route orchestration
    - Token estimation or provider behavior

Invariants/Assumptions:
    - Selected chunks may contain embedding blobs that must not be persisted.
    - Callers pass plain dict-like payloads or Pydantic models that can be
      serialized with the fallback sanitizer.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .. import db
from ..settings import Settings, get_settings


def record_interaction(
    *,
    endpoint: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    model: str | None,
    latency_ms: float | None,
    token_estimate: int | None,
    selected_chunks: Iterable[dict[str, Any]] | None = None,
    tool_calls: Iterable[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> None:
    """Persist a single interaction row."""
    settings = settings or get_settings()

    def _json_default(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        if hasattr(value, "__dict__"):
            return value.__dict__
        return str(value)

    sanitized_chunks: list[dict[str, Any]] = []
    if selected_chunks:
        for chunk in selected_chunks:
            chunk_map = dict(chunk)
            if "embedding_blob" in chunk_map:
                chunk_map["embedding_blob"] = None
            sanitized_chunks.append(chunk_map)

    payload = {
        "endpoint": endpoint,
        "model": model,
        "latency_ms": latency_ms,
        "request_payload": json.dumps(request_payload, default=_json_default),
        "response_payload": json.dumps(response_payload, default=_json_default),
        "tool_calls": json.dumps(list(tool_calls) if tool_calls else [], default=_json_default),
        "selected_chunks": json.dumps(sanitized_chunks, default=_json_default),
        "token_estimate": token_estimate,
    }
    with db.core_connection(settings) as conn:
        conn.execute(
            """
            INSERT INTO interactions (
                endpoint, model, latency_ms, request_payload,
                response_payload, tool_calls, selected_chunks, token_estimate
            )
            VALUES (:endpoint, :model, :latency_ms, :request_payload,
                    :response_payload, :tool_calls, :selected_chunks, :token_estimate)
            """,
            payload,
        )
        conn.commit()
