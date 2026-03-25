"""Shared HTTP streaming helpers for SSE-style transports.

Purpose:
    Centralize route-level streaming concerns shared by chat and RAG.

Responsibilities:
    - Prime generators before returning StreamingResponse.
    - Convert post-start exceptions into one canonical SSE error payload.
    - Keep streaming error handling consistent across recall transports.

Non-scope:
    - Shared chat or RAG execution semantics.
    - Frontend stream parsing or UI rendering.

Scope:
    - HTTP/SSE route helpers only.

Usage:
    - Imported by streaming FastAPI routes before constructing StreamingResponse.

Invariants/Assumptions:
    - Preflight failures should surface as normal HTTP errors before the response starts.
    - Post-start failures should terminate the stream with exactly one SSE error event.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from itertools import chain
from typing import TypeVar
from uuid import uuid4

from ..error_contract import error_view_from_exception, internal_error_view
from ..sse import format_sse_event

_StreamItem = TypeVar("_StreamItem")

logger = logging.getLogger(__name__)


def prime_stream(
    iterator: Iterator[_StreamItem],
) -> tuple[_StreamItem | None, Iterator[_StreamItem]]:
    """Advance one stream item so preflight failures happen before HTTP streaming starts."""
    try:
        first_item = next(iterator)
    except StopIteration:
        return None, iter(())
    return first_item, chain((first_item,), iterator)


def format_stream_error_event(exc: Exception) -> str:
    """Render one canonical SSE error event for a post-start failure."""
    try:
        view = error_view_from_exception(exc)
    except TypeError:
        error_id = str(uuid4())
        logger.exception("Unhandled streaming exception [%s]: %s", error_id, exc)
        view = internal_error_view(error_id=error_id)
    return format_sse_event(
        "error",
        {
            "error": {
                "type": view.error_type,
                "code": view.code,
                "message": view.message,
                "details": {"code": view.code, **view.details},
            }
        },
    )


__all__ = ["format_stream_error_event", "prime_stream"]
