"""Shared tool registration models.

Purpose:
    Define the transport-neutral tool metadata used by the public tool facade.

Responsibilities:
    - Describe callable tool executors
    - Represent canonical tool definitions once for all transports
    - Convert shared definitions into provider-specific tool specs

Scope:
    - Tool metadata and serialization helpers only

Non-scope:
    - Tool execution logic
    - Registry aggregation

Usage:
    - Imported by internal tool executor modules and registry builders

Invariants/Assumptions:
    - Tool definitions stay transport-neutral until serialization time
    - Executors return JSON-serializable dictionaries for chat/runtime use
    - Input schemas are object-style JSON Schema payloads
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..ai_bridge.protocol import BridgeToolSpec


class ToolExecutor(Protocol):
    """Callable contract for tool executors."""

    def __call__(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Canonical transport-neutral tool registration."""

    name: str
    description: str
    input_schema: dict[str, Any]
    executor: ToolExecutor
    manual_exposed: bool = True
    agent_exposed: bool = True

    def as_openai_tool_spec(self) -> dict[str, Any]:
        """Serialize the definition into the OpenAI/LiteLLM function-tool shape."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def as_bridge_tool_spec(self) -> BridgeToolSpec:
        """Serialize the definition into the pi bridge tool shape."""
        return BridgeToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )
