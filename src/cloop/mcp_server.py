"""MCP server entrypoint for Cloop tools.

Purpose:
    Assemble and run the FastMCP server that exposes loop, direct-memory,
    grounded chat, retrieval, and enrichment-review operations to external AI agents.

Responsibilities:
    - Create the shared FastMCP application instance
    - Register MCP tool modules with the server
    - Provide the stdio entrypoint used by `cloop-mcp`

Non-scope:
    - Tool business logic (see `mcp_tools/`)
    - MCP runtime decorators or error mapping (see `mcp_tools/_runtime.py`)
    - HTTP or CLI transport concerns

Invariants/Assumptions:
    - Tool modules own their own decorator application at registration time
    - This module should remain a thin server-assembly surface
"""

# =============================================================================
# MCP Tool Docstring Format
# =============================================================================
#
# All MCP tool docstrings should follow this format:
#
#     """One-line summary of tool purpose (under 80 chars).
#
#     Extended description explaining behavior, special cases, and usage notes.
#     Include any important warnings or edge cases here.
#
#     Args:
#         param_name: Description including type if non-obvious.
#             - Document valid options and defaults
#             - Note what happens if omitted for optional params
#
#     Returns:
#         Description of return value structure.
#         - Include field names for dict returns
#         - Note special cases (None, empty list, etc.)
#
#     Raises:
#         ToolError: Conditions that trigger this error.
#
# Notes:
#   - Always include Args and Returns sections (even if Args is empty)
#   - Use Raises section only if the tool can raise ToolError
#   - Keep one-line summary under 80 characters
# =============================================================================

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .mcp_tools import (
    register_chat_tools,
    register_loop_bulk_tools,
    register_loop_claim_tools,
    register_loop_core_tools,
    register_loop_dependency_tools,
    register_loop_read_tools,
    register_loop_relationship_tools,
    register_loop_template_tools,
    register_loop_view_tools,
    register_memory_tools,
    register_rag_tools,
    register_review_workflow_tools,
    register_suggestion_tools,
)

mcp = FastMCP("Cloop", json_response=True)

# Register all tool modules
register_chat_tools(mcp)
register_loop_core_tools(mcp)
register_loop_read_tools(mcp)
register_loop_relationship_tools(mcp)
register_loop_view_tools(mcp)
register_loop_bulk_tools(mcp)
register_loop_claim_tools(mcp)
register_loop_dependency_tools(mcp)
register_loop_template_tools(mcp)
register_memory_tools(mcp)
register_rag_tools(mcp)
register_review_workflow_tools(mcp)
register_suggestion_tools(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
