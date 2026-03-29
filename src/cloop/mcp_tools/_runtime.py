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
from typing import Callable, ParamSpec, TypeVar, cast

from mcp.server.fastmcp.exceptions import ToolError

from .. import db
from ..error_contract import error_view_from_exception
from ..loops.errors import CloopError
from ..settings import get_settings

P = ParamSpec("P")
R = TypeVar("R")


def with_db_init(func: Callable[P, R]) -> Callable[P, R]:
    """Initialize databases before executing an MCP tool handler."""

    @wraps(func)
    def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        settings = get_settings()
        db.init_databases(settings)
        return func(*args, **kwargs)

    return cast(Callable[P, R], _wrapper)


def to_tool_error(exc: Exception) -> ToolError:
    """Convert service layer exceptions to MCP ToolError with user-friendly messages."""
    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, CloopError):
        view = error_view_from_exception(exc)
        return ToolError(f"{view.code}: {view.message}")
    return ToolError(str(exc))


def with_mcp_error_handling(func: Callable[P, R]) -> Callable[P, R]:
    """Wrap an MCP tool handler to convert domain exceptions to ToolError."""

    @wraps(func)
    def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            raise to_tool_error(exc) from exc

    return cast(Callable[P, R], _wrapper)
