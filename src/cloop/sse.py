"""Shared SSE (Server-Sent Events) utilities.

Purpose:
    Provide streaming event delivery for real-time loop updates.

Responsibilities:
    - Sanitize SSE field values
    - Format events according to SSE spec

Non-scope:
    - WebSocket connections (not implemented)
    - Event persistence (see loops/repo.py)
"""

import json
from typing import Any

# Characters that could break SSE protocol if present in event/id fields
_SSE_FORBIDDEN_CHARS = "\n\r:"


def _sanitize_sse_field(value: str) -> str:
    """Remove characters that could break SSE protocol formatting.

    Args:
        value: Raw field value

    Returns:
        Sanitized value safe for SSE protocol
    """
    for char in _SSE_FORBIDDEN_CHARS:
        value = value.replace(char, "")
    return value


def format_sse_event(event: str, payload: dict[str, Any], *, event_id: str | None = None) -> str:
    """Format an SSE event string.

    Args:
        event: Event type/name
        payload: Event data (will be JSON serialized)
        event_id: Optional event ID for replay/cursor support

    Returns:
        Formatted SSE event string

    Raises:
        ValueError: If payload cannot be JSON serialized
    """
    # Sanitize event and event_id to prevent SSE protocol injection
    sanitized_event = _sanitize_sse_field(event)
    sanitized_event_id = _sanitize_sse_field(event_id) if event_id else None

    # Attempt JSON serialization with clear error handling
    try:
        data = json.dumps(payload)
    except TypeError as e:
        raise ValueError(f"Payload cannot be JSON serialized: {e}") from e

    lines = []
    if sanitized_event_id:
        lines.append(f"id: {sanitized_event_id}")
    lines.append(f"event: {sanitized_event}")
    lines.append(f"data: {data}")
    lines.append("")  # Empty line to terminate event
    lines.append("")
    return "\n".join(lines)


def format_sse_comment(text: str) -> str:
    """Format an SSE comment (used for heartbeats/keepalive).

    Args:
        text: Comment text

    Returns:
        Formatted SSE comment line
    """
    return f": {text}\n\n"
