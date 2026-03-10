"""Shared MCP runtime decorators and error mapping.

Purpose:
    Centralize MCP-specific database initialization and domain-error mapping so
    tool modules depend on a focused runtime helper instead of the server
    assembly module.

Responsibilities:
    - Initialize databases before MCP tool execution
    - Convert domain exceptions into FastMCP ToolError instances
    - Provide decorators reusable across all MCP tool modules

Non-scope:
    - MCP tool registration
    - MCP server creation or transport wiring
    - Tool business logic implementations

Invariants/Assumptions:
    - Domain exceptions retain their user-facing message payloads
    - Unknown exceptions are surfaced as ToolError with their string message
    - Database initialization must run before any tool handler touches storage
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from mcp.server.fastmcp.exceptions import ToolError

from .. import db
from ..loops.errors import (
    ClaimNotFoundError,
    CloopError,
    DependencyCycleError,
    LoopClaimedError,
    NotFoundError,
    TransitionError,
    UndoNotPossibleError,
    ValidationError,
)
from ..settings import get_settings

F = TypeVar("F", bound=Callable[..., Any])


def with_db_init(func: F) -> F:
    """Initialize databases before executing an MCP tool handler."""

    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        settings = get_settings()
        db.init_databases(settings)
        return func(*args, **kwargs)

    return _wrapper  # type: ignore[return-value]


def to_tool_error(exc: Exception) -> ToolError:
    """Convert service layer exceptions to MCP ToolError with user-friendly messages."""
    if isinstance(exc, ToolError):
        return exc
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
    return ToolError(str(exc))


def with_mcp_error_handling(func: F) -> F:
    """Wrap an MCP tool handler to convert domain exceptions to ToolError."""

    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            raise to_tool_error(exc) from exc

    return _wrapper  # type: ignore[return-value]
