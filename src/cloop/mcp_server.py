"""MCP server exposing loop operations to external AI agents.

Purpose:
    Expose loop operations via Model Context Protocol for AI agent integration.

Responsibilities:
    - FastMCP server setup and configuration
    - Shared decorators (with_db_init, with_mcp_error_handling)
    - Idempotency helper functions
    - Tool module registration

Non-scope:
    - Tool implementations (see mcp_tools/ package)
    - HTTP REST API (see routes/)
    - CLI interface (see cli.py)

Idempotency:
    All mutation tools support an optional `request_id` parameter for safe retries.
    Same request_id + same args replays prior response without additional writes.
    Same request_id + different args raises ToolError.
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

from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import db
from .loops import enrichment as loop_enrichment  # noqa: F401
from .loops.errors import (
    ClaimNotFoundError,
    CloopError,
    DependencyCycleError,
    LoopClaimedError,
    NotFoundError,
    TransitionError,
    UndoNotPossibleError,
    ValidationError,
)
from .mcp_tools.loop_bulk import (
    loop_bulk_close as _loop_bulk_close,
)
from .mcp_tools.loop_bulk import (
    loop_bulk_snooze as _loop_bulk_snooze,
)
from .mcp_tools.loop_bulk import (
    loop_bulk_update as _loop_bulk_update,
)
from .mcp_tools.loop_claims import (
    loop_claim as _loop_claim,
)
from .mcp_tools.loop_claims import (
    loop_force_release_claim as _loop_force_release_claim,
)
from .mcp_tools.loop_claims import (
    loop_get_claim as _loop_get_claim,
)
from .mcp_tools.loop_claims import (
    loop_list_claims as _loop_list_claims,
)
from .mcp_tools.loop_claims import (
    loop_release_claim as _loop_release_claim,
)
from .mcp_tools.loop_claims import (
    loop_renew_claim as _loop_renew_claim,
)
from .mcp_tools.loop_core import (
    loop_close as _loop_close,
)
from .mcp_tools.loop_core import (
    loop_create as _loop_create,
)
from .mcp_tools.loop_core import (
    loop_get as _loop_get,
)
from .mcp_tools.loop_core import (
    loop_transition as _loop_transition,
)
from .mcp_tools.loop_core import (
    loop_update as _loop_update,
)
from .mcp_tools.loop_dependencies import (
    loop_dependency_add as _loop_dependency_add,
)
from .mcp_tools.loop_dependencies import (
    loop_dependency_blocking as _loop_dependency_blocking,
)
from .mcp_tools.loop_dependencies import (
    loop_dependency_list as _loop_dependency_list,
)
from .mcp_tools.loop_dependencies import (
    loop_dependency_remove as _loop_dependency_remove,
)
from .mcp_tools.loop_read import (
    loop_enrich as _loop_enrich,
)
from .mcp_tools.loop_read import (
    loop_events as _loop_events,
)
from .mcp_tools.loop_read import (
    loop_list as _loop_list,
)
from .mcp_tools.loop_read import (
    loop_next as _loop_next,
)
from .mcp_tools.loop_read import (
    loop_search as _loop_search,
)
from .mcp_tools.loop_read import (
    loop_snooze as _loop_snooze,
)
from .mcp_tools.loop_read import (
    loop_tags as _loop_tags,
)
from .mcp_tools.loop_read import (
    loop_undo as _loop_undo,
)
from .mcp_tools.loop_templates import (
    loop_template_create as _loop_template_create,
)
from .mcp_tools.loop_templates import (
    loop_template_delete as _loop_template_delete,
)
from .mcp_tools.loop_templates import (
    loop_template_from_loop as _loop_template_from_loop,
)
from .mcp_tools.loop_templates import (
    loop_template_get as _loop_template_get,
)
from .mcp_tools.loop_templates import (
    loop_template_list as _loop_template_list,
)
from .mcp_tools.loop_templates import (
    project_list as _project_list,
)
from .mcp_tools.loop_views import (
    loop_view_apply as _loop_view_apply,
)
from .mcp_tools.loop_views import (
    loop_view_create as _loop_view_create,
)
from .mcp_tools.loop_views import (
    loop_view_delete as _loop_view_delete,
)
from .mcp_tools.loop_views import (
    loop_view_get as _loop_view_get,
)
from .mcp_tools.loop_views import (
    loop_view_list as _loop_view_list,
)
from .mcp_tools.loop_views import (
    loop_view_update as _loop_view_update,
)
from .settings import get_settings

if TYPE_CHECKING:
    pass

mcp = FastMCP("Cloop Loops", json_response=True)

F = TypeVar("F", bound=Callable[..., Any])


def with_db_init(func: F) -> F:
    """Initialize databases before executing an MCP tool handler.

    Ensures settings are loaded and databases are initialized before any
    MCP tool operation. This centralizes initialization logic that was
    previously duplicated across all handlers.
    """

    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        settings = get_settings()
        db.init_databases(settings)
        return func(*args, **kwargs)

    return _wrapper  # type: ignore[return-value]


def _to_tool_error(exc: Exception) -> ToolError:
    """Convert service layer exceptions to MCP ToolError with user-friendly message."""
    if isinstance(exc, NotFoundError):
        return ToolError(exc.message)
    if isinstance(exc, TransitionError):
        return ToolError(f"Invalid status transition: {exc.from_status} -> {exc.to_status}")
    if isinstance(exc, ValidationError):
        return ToolError(exc.message)
    if isinstance(exc, LoopClaimedError):
        return ToolError(f"Loop {exc.loop_id} is claimed by '{exc.owner}' until {exc.lease_until}")
    if isinstance(exc, ClaimNotFoundError):
        return ToolError(exc.message)
    if isinstance(exc, DependencyCycleError):
        return ToolError(exc.message)
    if isinstance(exc, UndoNotPossibleError):
        return ToolError(f"Cannot undo: {exc.message}")
    if isinstance(exc, CloopError):
        return ToolError(exc.message)

    # Unknown exception type - pass through the message
    return ToolError(str(exc))


def with_mcp_error_handling(func: F) -> F:
    """Wrap MCP tool handler to convert exceptions to ToolError.

    Catches both typed CloopError and legacy ValueError for consistent
    error responses to MCP clients.
    """

    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            raise _to_tool_error(exc) from exc

    return _wrapper  # type: ignore[return-value]


# Re-export tool functions with error handling for backwards compatibility
loop_create = with_mcp_error_handling(_loop_create)
loop_update = with_mcp_error_handling(_loop_update)
loop_close = with_mcp_error_handling(_loop_close)
loop_get = with_mcp_error_handling(_loop_get)
loop_transition = with_mcp_error_handling(_loop_transition)
loop_list = with_mcp_error_handling(_loop_list)
loop_search = with_mcp_error_handling(_loop_search)
loop_snooze = with_mcp_error_handling(_loop_snooze)
loop_enrich = with_mcp_error_handling(_loop_enrich)
loop_events = with_mcp_error_handling(_loop_events)
loop_undo = with_mcp_error_handling(_loop_undo)
loop_next = with_mcp_error_handling(_loop_next)
loop_tags = with_mcp_error_handling(_loop_tags)
loop_view_create = with_mcp_error_handling(_loop_view_create)
loop_view_list = with_mcp_error_handling(_loop_view_list)
loop_view_get = with_mcp_error_handling(_loop_view_get)
loop_view_update = with_mcp_error_handling(_loop_view_update)
loop_view_delete = with_mcp_error_handling(_loop_view_delete)
loop_view_apply = with_mcp_error_handling(_loop_view_apply)
loop_bulk_update = with_mcp_error_handling(_loop_bulk_update)
loop_bulk_close = with_mcp_error_handling(_loop_bulk_close)
loop_bulk_snooze = with_mcp_error_handling(_loop_bulk_snooze)
loop_claim = with_mcp_error_handling(_loop_claim)
loop_renew_claim = with_mcp_error_handling(_loop_renew_claim)
loop_release_claim = with_mcp_error_handling(_loop_release_claim)
loop_get_claim = with_mcp_error_handling(_loop_get_claim)
loop_list_claims = with_mcp_error_handling(_loop_list_claims)
loop_force_release_claim = with_mcp_error_handling(_loop_force_release_claim)
loop_dependency_add = with_mcp_error_handling(_loop_dependency_add)
loop_dependency_remove = with_mcp_error_handling(_loop_dependency_remove)
loop_dependency_list = with_mcp_error_handling(_loop_dependency_list)
loop_dependency_blocking = with_mcp_error_handling(_loop_dependency_blocking)
loop_template_list = with_mcp_error_handling(_loop_template_list)
loop_template_get = with_mcp_error_handling(_loop_template_get)
loop_template_create = with_mcp_error_handling(_loop_template_create)
loop_template_delete = with_mcp_error_handling(_loop_template_delete)
loop_template_from_loop = with_mcp_error_handling(_loop_template_from_loop)
project_list = with_mcp_error_handling(_project_list)

# Import registration functions after re-exports to avoid circular imports  # noqa: E402
from .mcp_tools import (  # noqa: E402
    register_loop_bulk_tools,
    register_loop_claim_tools,
    register_loop_core_tools,
    register_loop_dependency_tools,
    register_loop_read_tools,
    register_loop_template_tools,
    register_loop_view_tools,
)

# Register all tool modules
register_loop_core_tools(mcp)
register_loop_read_tools(mcp)
register_loop_view_tools(mcp)
register_loop_bulk_tools(mcp)
register_loop_claim_tools(mcp)
register_loop_dependency_tools(mcp)
register_loop_template_tools(mcp)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
