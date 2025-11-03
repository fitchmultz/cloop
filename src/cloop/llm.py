from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple, cast

import litellm

from .settings import Settings, get_settings

Message = Dict[str, Any]


def estimate_tokens(messages: List[Message]) -> int:
    return sum(len((message.get("content") or "").split()) for message in messages)


def chat_completion(
    messages: List[Message],
    *,
    settings: Settings | None = None,
) -> Tuple[str, Dict[str, Any]]:
    settings = settings or get_settings()
    start = time.time()
    response = cast(
        Dict[str, Any],
        litellm.completion(
            model=settings.llm_model,
            messages=messages,
            timeout=int(settings.llm_timeout),
        ),
    )
    latency_ms = (time.time() - start) * 1000
    choices = cast(List[Dict[str, Any]], response.get("choices", []))
    content = ""
    if choices:
        message = cast(Dict[str, Any], choices[0].get("message", {}))
        content = str(message.get("content", ""))
    metadata = {
        "latency_ms": latency_ms,
        "model": response.get("model") or settings.llm_model,
        "usage": response.get("usage", {}),
    }
    return content, metadata
