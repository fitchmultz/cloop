"""Public tool executor and registry facade.

Purpose:
    Expose the canonical `cloop.tools` import surface while delegating
    implementation details to focused internal modules.

Responsibilities:
    - Re-export tool executors used by chat/runtime/tests
    - Re-export the canonical tool registry and lookup helpers
    - Keep the public tool surface stable while internal ownership stays focused

Scope:
    - Public facade only

Non-scope:
    - Tool execution internals
    - Tool-definition assembly details

Usage:
    - Import executors, tool definitions, and registry helpers from here
    - Internal implementation lives under `cloop._tools`

Invariants/Assumptions:
    - `cloop.tools` remains the public import surface for callers
    - Domain-specific tool behavior lives in focused internal modules
    - Tool ordering and names are defined by the shared internal registry
"""

from __future__ import annotations

from ._tools.loops import (
    execute_loop_close,
    execute_loop_create,
    execute_loop_enrich,
    execute_loop_get,
    execute_loop_list,
    execute_loop_next,
    execute_loop_search,
    execute_loop_snooze,
    execute_loop_transition,
    execute_loop_update,
)
from ._tools.memory import (
    execute_memory_create,
    execute_memory_delete,
    execute_memory_search,
    execute_memory_update,
)
from ._tools.models import ToolDefinition, ToolExecutor
from ._tools.notes import (
    execute_list_notes,
    execute_read_note,
    execute_search_notes,
    execute_write_note,
)
from ._tools.registry import (
    AGENT_TOOL_SPECS,
    EXECUTORS,
    MANUAL_TOOL_NAMES,
    TOOL_DEFINITIONS,
    TOOL_SPECS,
    get_agent_bridge_tools,
    get_tool_definition,
)
from ._tools.validation import _require_fields, normalize_tool_arguments

__all__ = [
    "AGENT_TOOL_SPECS",
    "EXECUTORS",
    "MANUAL_TOOL_NAMES",
    "TOOL_DEFINITIONS",
    "TOOL_SPECS",
    "ToolDefinition",
    "ToolExecutor",
    "_require_fields",
    "execute_list_notes",
    "execute_loop_close",
    "execute_loop_create",
    "execute_loop_enrich",
    "execute_loop_get",
    "execute_loop_list",
    "execute_loop_next",
    "execute_loop_search",
    "execute_loop_snooze",
    "execute_loop_transition",
    "execute_loop_update",
    "execute_memory_create",
    "execute_memory_delete",
    "execute_memory_search",
    "execute_memory_update",
    "execute_read_note",
    "execute_search_notes",
    "execute_write_note",
    "get_agent_bridge_tools",
    "get_tool_definition",
    "normalize_tool_arguments",
]
