"""MCP tool modules for loop, direct-memory, chat, retrieval, and review operations.

This package contains domain-separated MCP tool implementations.
Each module registers its tools with the central FastMCP instance.
"""

from .chat_tools import register_chat_tools
from .loop_bulk import register_loop_bulk_tools
from .loop_claims import register_loop_claim_tools
from .loop_core import register_loop_core_tools
from .loop_dependencies import register_loop_dependency_tools
from .loop_read import register_loop_read_tools
from .loop_relationships import register_loop_relationship_tools
from .loop_templates import register_loop_template_tools
from .loop_views import register_loop_view_tools
from .memory_tools import register_memory_tools
from .rag_tools import register_rag_tools
from .review_workflows import register_review_workflow_tools
from .suggestion_tools import register_suggestion_tools

__all__ = [
    "register_chat_tools",
    "register_loop_bulk_tools",
    "register_loop_claim_tools",
    "register_loop_core_tools",
    "register_loop_dependency_tools",
    "register_loop_read_tools",
    "register_loop_relationship_tools",
    "register_loop_template_tools",
    "register_loop_view_tools",
    "register_memory_tools",
    "register_rag_tools",
    "register_review_workflow_tools",
    "register_suggestion_tools",
]
