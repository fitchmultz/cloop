"""MCP server exposing loop operations to external AI agents.

This module implements the Model Context Protocol (MCP) server that allows
external AI agents to interact with Cloop's loop management system. All
operations are exposed as MCP tools with JSON responses.

Tool Handlers:
    - loop.create: Capture a new loop
    - loop.update: Update loop fields
    - loop.close: Close a loop as completed/dropped
    - loop.list: List loops with optional status filter
    - loop.search: Search loops by text
    - loop.snooze: Set snooze timer on a loop
    - loop.enrich: Trigger AI enrichment for a loop
    - project.list: List all projects

Non-scope:
    - HTTP API endpoints (see main.py)
    - CLI commands (see cli.py)
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import db
from .loops import enrichment as loop_enrichment
from .loops import repo as loop_repo
from .loops import service as loop_service
from .loops.models import LoopStatus, validate_iso8601_timestamp
from .settings import get_settings

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


def _to_tool_error(exc: ValueError) -> ToolError:
    """Convert service layer ValueError to MCP ToolError with user-friendly message.

    Uses the same error pattern matching as main.py HTTP error handling
    to ensure consistency across interfaces.
    """
    message = str(exc)

    # Map "not_found" errors (same pattern as main.py)
    if "not_found" in message:
        # Convert snake_case to human-readable
        if "loop_not_found" in message:
            return ToolError("Loop not found")
        if "project_not_found" in message:
            return ToolError("Project not found")
        return ToolError("Resource not found")

    # Map validation errors (invalid_*)
    if message.startswith("invalid_"):
        # Convert invalid_captured_at -> "Invalid captured_at timestamp"
        field = message.split(":")[0].replace("invalid_", "")
        return ToolError(f"Invalid {field.replace('_', ' ')}")

    # Map transition errors
    if "invalid_transition" in message or "status_update_requires_transition" in message:
        return ToolError(f"Invalid status transition: {message}")

    # Map completion/dropping errors
    if "status must be completed or dropped" in message:
        return ToolError("Status must be 'completed' or 'dropped'")

    # Default: pass through the original message
    return ToolError(message)


def with_mcp_error_handling(func: F) -> F:
    """Wrap MCP tool handler to convert ValueError to ToolError.

    Provides consistent error handling across all MCP tools by catching
    ValueError from the service layer and converting it to structured
    ToolError responses for MCP clients.
    """

    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ValueError as exc:
            raise _to_tool_error(exc) from exc

    return _wrapper  # type: ignore[return-value]


@mcp.tool(name="loop.create")
@with_db_init
@with_mcp_error_handling
def loop_create(
    raw_text: str,
    captured_at: str,
    client_tz_offset_min: int,
    status: str = "inbox",
) -> dict[str, Any]:
    # Validate timestamp format before processing
    validate_iso8601_timestamp(captured_at, "captured_at")

    settings = get_settings()
    loop_status = LoopStatus(status)
    with db.core_connection(settings) as conn:
        record = loop_service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=client_tz_offset_min,
            status=loop_status,
            conn=conn,
        )
    return record


@mcp.tool(name="loop.update")
@with_db_init
@with_mcp_error_handling
def loop_update(loop_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    # Validate timestamp fields in the fields dict
    if "due_at_utc" in fields and fields["due_at_utc"] is not None:
        validate_iso8601_timestamp(fields["due_at_utc"], "due_at_utc")
    if "snooze_until_utc" in fields and fields["snooze_until_utc"] is not None:
        validate_iso8601_timestamp(fields["snooze_until_utc"], "snooze_until_utc")

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.update_loop(loop_id=loop_id, fields=fields, conn=conn)


@mcp.tool(name="loop.close")
@with_db_init
@with_mcp_error_handling
def loop_close(
    loop_id: int,
    status: str = "completed",
    note: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    loop_status = LoopStatus(status)
    if loop_status not in {LoopStatus.COMPLETED, LoopStatus.DROPPED}:
        raise ValueError("status must be completed or dropped")
    with db.core_connection(settings) as conn:
        return loop_service.transition_status(
            loop_id=loop_id,
            to_status=loop_status,
            note=note,
            conn=conn,
        )


@mcp.tool(name="loop.list")
@with_db_init
@with_mcp_error_handling
def loop_list(status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    settings = get_settings()
    parsed_status = LoopStatus(status) if status else None
    with db.core_connection(settings) as conn:
        return loop_service.list_loops(
            status=parsed_status,
            limit=limit,
            offset=offset,
            conn=conn,
        )


@mcp.tool(name="loop.search")
@with_db_init
@with_mcp_error_handling
def loop_search(query: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.search_loops(query=query, limit=limit, offset=offset, conn=conn)


@mcp.tool(name="loop.snooze")
@with_db_init
@with_mcp_error_handling
def loop_snooze(loop_id: int, snooze_until_utc: str) -> dict[str, Any]:
    # Validate timestamp format before processing
    validate_iso8601_timestamp(snooze_until_utc, "snooze_until_utc")

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.update_loop(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until_utc},
            conn=conn,
        )


@mcp.tool(name="loop.enrich")
@with_db_init
@with_mcp_error_handling
def loop_enrich(loop_id: int) -> dict[str, Any]:
    settings = get_settings()
    with db.core_connection(settings) as conn:
        loop_service.request_enrichment(loop_id=loop_id, conn=conn)
        result = loop_enrichment.enrich_loop(loop_id=loop_id, conn=conn, settings=settings)
    return result


@mcp.tool(name="project.list")
@with_db_init
@with_mcp_error_handling
def project_list() -> list[dict[str, Any]]:
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.list_projects(conn=conn)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
