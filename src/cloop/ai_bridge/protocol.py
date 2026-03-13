"""Strict JSONL protocol for the pi bridge.

Purpose:
    Centralize the Python-side message envelopes used to communicate with the
    Node bridge process.

Responsibilities:
    - Define protocol version and envelope builders
    - Validate minimal shape of incoming JSONL messages
    - Keep request/response payloads stable and explicit

Non-scope:
    - Subprocess lifecycle management (see runtime.py)
    - Route-specific orchestration (see llm.py)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .errors import BridgeProtocolError

PROTOCOL_VERSION = 1
TERMINAL_EVENT_TYPES = frozenset({"done", "error"})


@dataclass(frozen=True, slots=True)
class BridgeToolSpec:
    """Transport-neutral tool schema sent to the Node bridge."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BridgeStartRequest:
    """Start request sent from Python to the Node bridge."""

    request_id: str
    model: str
    messages: list[dict[str, Any]]
    thinking_level: str
    timeout_ms: int
    max_tool_rounds: int
    tools: list[BridgeToolSpec]


def encode_line(payload: dict[str, Any]) -> bytes:
    """Serialize one protocol message as UTF-8 JSONL."""
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def build_start_message(request: BridgeStartRequest) -> dict[str, Any]:
    """Build a start envelope for one request."""
    return {
        "type": "start",
        "protocol": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "model": request.model,
        "messages": request.messages,
        "thinking_level": request.thinking_level,
        "timeout_ms": request.timeout_ms,
        "max_tool_rounds": request.max_tool_rounds,
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in request.tools
        ],
    }


def build_tool_result_message(
    *,
    request_id: str,
    tool_call_id: str,
    payload: dict[str, Any],
    is_error: bool,
) -> dict[str, Any]:
    """Build a tool result envelope returning Python execution output."""
    return {
        "type": "tool_result",
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
        "tool_call_id": tool_call_id,
        "payload": payload,
        "is_error": is_error,
    }


def build_abort_message(*, request_id: str) -> dict[str, Any]:
    """Build an abort envelope for an in-flight request."""
    return {
        "type": "abort",
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
    }


def build_ping_message(*, request_id: str) -> dict[str, Any]:
    """Build a ping envelope used for readiness checks."""
    return {
        "type": "ping",
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
    }


def parse_line(raw_line: str) -> dict[str, Any]:
    """Parse and minimally validate one JSONL event from the bridge."""
    try:
        payload = json.loads(raw_line)
    except json.JSONDecodeError as exc:
        raise BridgeProtocolError(f"Malformed bridge JSONL: {exc}") from exc
    if not isinstance(payload, dict):
        raise BridgeProtocolError("Bridge payload must be a JSON object")
    payload_type = payload.get("type")
    if not isinstance(payload_type, str) or not payload_type:
        raise BridgeProtocolError("Bridge payload missing string 'type'")
    protocol = payload.get("protocol")
    if protocol != PROTOCOL_VERSION:
        raise BridgeProtocolError(
            f"Bridge protocol mismatch: expected {PROTOCOL_VERSION}, received {protocol!r}"
        )
    return payload
