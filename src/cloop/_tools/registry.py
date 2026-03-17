"""Tool-registry assembly for the public `cloop.tools` facade.

Purpose:
    Assemble the canonical transport-neutral tool registry from focused domain modules.

Responsibilities:
    - Combine domain-specific tool definitions in stable order
    - Normalize schemas for provider compatibility
    - Expose derived registries used by chat/runtime code

Scope:
    - Tool-definition aggregation and lookup only

Non-scope:
    - Tool executor implementations
    - Chat/runtime call orchestration

Usage:
    - Imported by `cloop.tools` to expose the public registry constants

Invariants/Assumptions:
    - Tool ordering is stable across transports and releases
    - Domain modules own executor behavior and human-facing descriptions
    - The registry remains the single source for exposed tool names/specs
"""

from __future__ import annotations

from ..ai_bridge.protocol import BridgeToolSpec
from .loops import LOOP_TOOL_DEFINITIONS
from .memory import MEMORY_TOOL_DEFINITIONS
from .models import ToolDefinition, ToolExecutor
from .notes import NOTE_TOOL_DEFINITIONS
from .validation import _closed_object_schema


def _normalize_definition(definition: ToolDefinition) -> ToolDefinition:
    """Normalize one tool definition for provider compatibility."""
    return ToolDefinition(
        name=definition.name,
        description=definition.description,
        input_schema=_closed_object_schema(definition.input_schema),
        executor=definition.executor,
        manual_exposed=definition.manual_exposed,
        agent_exposed=definition.agent_exposed,
    )


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(
    _normalize_definition(definition)
    for definition in (*NOTE_TOOL_DEFINITIONS, *LOOP_TOOL_DEFINITIONS, *MEMORY_TOOL_DEFINITIONS)
)
TOOL_SPECS: list[dict[str, object]] = [tool.as_openai_tool_spec() for tool in TOOL_DEFINITIONS]
AGENT_TOOL_SPECS: list[dict[str, object]] = [
    tool.as_openai_tool_spec() for tool in TOOL_DEFINITIONS if tool.agent_exposed
]
MANUAL_TOOL_NAMES = frozenset(tool.name for tool in TOOL_DEFINITIONS if tool.manual_exposed)
EXECUTORS: dict[str, ToolExecutor] = {tool.name: tool.executor for tool in TOOL_DEFINITIONS}
_TOOL_DEFINITIONS_BY_NAME = {tool.name: tool for tool in TOOL_DEFINITIONS}


def get_tool_definition(name: str) -> ToolDefinition | None:
    """Return the canonical tool definition for one tool name."""
    return _TOOL_DEFINITIONS_BY_NAME.get(name)


def get_agent_bridge_tools() -> list[BridgeToolSpec]:
    """Return the pi bridge tool set exposed to agent-driven execution."""
    return [tool.as_bridge_tool_spec() for tool in TOOL_DEFINITIONS if tool.agent_exposed]
