"""MCP tools for saved review actions and review sessions.

Purpose:
    Re-export feature-owned MCP review workflow tool modules behind the
    canonical `cloop.mcp_tools.review_workflows` surface.

Responsibilities:
    - Preserve one stable registration surface for review workflow MCP tools
    - Keep relationship and enrichment MCP wrappers organized by domain

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Public MCP tool facade only
    - No inline review workflow or MCP mutation logic

Usage:
    Imported by `cloop.mcp_tools` and MCP server assembly.

Invariants/Assumptions:
    - Tool names and operator-facing docstrings stay unchanged
    - Relationship and enrichment tools are registered together by the facade
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._review_workflows.enrichment import (
    register_enrichment_review_workflow_tools,
    review_enrichment_action_create,
    review_enrichment_action_delete,
    review_enrichment_action_get,
    review_enrichment_action_list,
    review_enrichment_action_update,
    review_enrichment_session_answer_clarifications,
    review_enrichment_session_apply_action,
    review_enrichment_session_create,
    review_enrichment_session_delete,
    review_enrichment_session_get,
    review_enrichment_session_list,
    review_enrichment_session_move,
    review_enrichment_session_refresh,
    review_enrichment_session_update,
)
from ._review_workflows.relationship import (
    register_relationship_review_workflow_tools,
    review_relationship_action_create,
    review_relationship_action_delete,
    review_relationship_action_get,
    review_relationship_action_list,
    review_relationship_action_update,
    review_relationship_session_apply_action,
    review_relationship_session_create,
    review_relationship_session_delete,
    review_relationship_session_get,
    review_relationship_session_list,
    review_relationship_session_move,
    review_relationship_session_refresh,
    review_relationship_session_update,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_review_workflow_tools(mcp: "FastMCP") -> None:
    """Register review workflow MCP tools."""
    register_relationship_review_workflow_tools(mcp)
    register_enrichment_review_workflow_tools(mcp)


__all__ = [
    "register_review_workflow_tools",
    "review_relationship_action_create",
    "review_relationship_action_list",
    "review_relationship_action_get",
    "review_relationship_action_update",
    "review_relationship_action_delete",
    "review_relationship_session_create",
    "review_relationship_session_list",
    "review_relationship_session_get",
    "review_relationship_session_move",
    "review_relationship_session_refresh",
    "review_relationship_session_update",
    "review_relationship_session_delete",
    "review_relationship_session_apply_action",
    "review_enrichment_action_create",
    "review_enrichment_action_list",
    "review_enrichment_action_get",
    "review_enrichment_action_update",
    "review_enrichment_action_delete",
    "review_enrichment_session_create",
    "review_enrichment_session_list",
    "review_enrichment_session_get",
    "review_enrichment_session_move",
    "review_enrichment_session_refresh",
    "review_enrichment_session_update",
    "review_enrichment_session_delete",
    "review_enrichment_session_apply_action",
    "review_enrichment_session_answer_clarifications",
]
