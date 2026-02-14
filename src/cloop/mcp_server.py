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

Idempotency:
    All mutation tools support an optional `request_id` parameter for safe retries.
    Same request_id + same args replays prior response without additional writes.
    Same request_id + different args raises ToolError.

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
from .constants import DEFAULT_LOOP_LIST_LIMIT
from .idempotency import (
    IdempotencyConflictError,
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from .loops import enrichment as loop_enrichment
from .loops import repo as loop_repo
from .loops import service as loop_service
from .loops.errors import (
    CloopError,
    NotFoundError,
    TransitionError,
    ValidationError,
)
from .loops.models import (
    LoopStatus,
    is_terminal_status,
    validate_iso8601_timestamp,
    validate_tz_offset,
)
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


def _to_tool_error(exc: Exception) -> ToolError:
    """Convert service layer exceptions to MCP ToolError with user-friendly message."""
    if isinstance(exc, NotFoundError):
        return ToolError(exc.message)
    if isinstance(exc, TransitionError):
        return ToolError(f"Invalid status transition: {exc.from_status} -> {exc.to_status}")
    if isinstance(exc, ValidationError):
        return ToolError(exc.message)
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


def _handle_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    settings: Any,
) -> dict[str, Any] | None:
    """Handle idempotency for MCP tool calls.

    Args:
        tool_name: MCP tool name (e.g., "loop.create")
        request_id: Optional idempotency key
        payload: Request payload (will be hashed)
        settings: Settings object

    Returns:
        None if should proceed with mutation, or replayed response dict

    Raises:
        ToolError: If idempotency key conflict or validation error
    """
    if request_id is None:
        return None

    try:
        key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    except ValueError as e:
        raise ToolError(str(e)) from None

    scope = build_mcp_scope(tool_name)
    request_hash = canonical_request_hash(payload)
    expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

    with db.core_connection(settings) as conn:
        try:
            claim = db.claim_or_replay_idempotency(
                scope=scope,
                idempotency_key=key,
                request_hash=request_hash,
                expires_at=expires_at,
                conn=conn,
            )
        except IdempotencyConflictError as e:
            raise ToolError(f"Idempotency conflict: {e}") from None

        if not claim["is_new"] and claim["replay"]:
            return claim["replay"]["response_body"]

        return None


def _finalize_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    response: dict[str, Any],
    settings: Any,
) -> None:
    """Store response for idempotent MCP tool call.

    Args:
        tool_name: MCP tool name
        request_id: Optional idempotency key
        payload: Request payload
        response: Response body to store
        settings: Settings object
    """
    if request_id is None:
        return

    key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    scope = build_mcp_scope(tool_name)

    with db.core_connection(settings) as conn:
        db.finalize_idempotency_response(
            scope=scope,
            idempotency_key=key,
            response_status=200,
            response_body=response,
            conn=conn,
        )


@mcp.tool(name="loop.create")
@with_db_init
@with_mcp_error_handling
def loop_create(
    raw_text: str,
    captured_at: str,
    client_tz_offset_min: int,
    status: str = "inbox",
    request_id: str | None = None,
) -> dict[str, Any]:
    validate_iso8601_timestamp(captured_at, "captured_at")
    validate_tz_offset(client_tz_offset_min, "client_tz_offset_min")

    settings = get_settings()
    loop_status = LoopStatus(status)

    payload = {
        "raw_text": raw_text,
        "captured_at": captured_at,
        "client_tz_offset_min": client_tz_offset_min,
        "status": status,
    }

    replay = _handle_mcp_idempotency(
        tool_name="loop.create",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        record = loop_service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=client_tz_offset_min,
            status=loop_status,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.create",
        request_id=request_id,
        payload=payload,
        response=record,
        settings=settings,
    )
    return record


@mcp.tool(name="loop.update")
@with_db_init
@with_mcp_error_handling
def loop_update(
    loop_id: int,
    fields: dict[str, Any],
    request_id: str | None = None,
) -> dict[str, Any]:
    if "due_at_utc" in fields and fields["due_at_utc"] is not None:
        validate_iso8601_timestamp(fields["due_at_utc"], "due_at_utc")
    if "snooze_until_utc" in fields and fields["snooze_until_utc"] is not None:
        validate_iso8601_timestamp(fields["snooze_until_utc"], "snooze_until_utc")

    settings = get_settings()

    payload = {"loop_id": loop_id, "fields": fields}

    replay = _handle_mcp_idempotency(
        tool_name="loop.update",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.update_loop(loop_id=loop_id, fields=fields, conn=conn)

    _finalize_mcp_idempotency(
        tool_name="loop.update",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.close")
@with_db_init
@with_mcp_error_handling
def loop_close(
    loop_id: int,
    status: str = "completed",
    note: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    loop_status = LoopStatus(status)
    if not is_terminal_status(loop_status):
        raise ValidationError("status", "must be completed or dropped")

    payload = {"loop_id": loop_id, "status": status, "note": note}

    replay = _handle_mcp_idempotency(
        tool_name="loop.close",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.transition_status(
            loop_id=loop_id,
            to_status=loop_status,
            note=note,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.close",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.list")
@with_db_init
@with_mcp_error_handling
def loop_list(
    status: str | None = None, limit: int = DEFAULT_LOOP_LIST_LIMIT, offset: int = 0
) -> list[dict[str, Any]]:
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
def loop_search(
    query: str, limit: int = DEFAULT_LOOP_LIST_LIMIT, offset: int = 0
) -> list[dict[str, Any]]:
    """Search loops using the DSL query language.

    Query syntax:
        - status:<value> where value in {open, all, inbox, actionable,
          blocked, scheduled, completed, dropped}
        - tag:<value>
        - project:<value>
        - due:<value> where value in {today, tomorrow, overdue, none, next7d}
        - text:<value>
        - Bare tokens without field: prefix are treated as text:<token>

    Examples:
        - "status:inbox tag:work due:today"
        - "project:ClientAlpha blocked"
        - "status:open groceries"
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.search_loops_by_query(
            query=query, limit=limit, offset=offset, conn=conn
        )


@mcp.tool(name="loop.snooze")
@with_db_init
@with_mcp_error_handling
def loop_snooze(
    loop_id: int,
    snooze_until_utc: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    validate_iso8601_timestamp(snooze_until_utc, "snooze_until_utc")

    settings = get_settings()

    payload = {"loop_id": loop_id, "snooze_until_utc": snooze_until_utc}

    replay = _handle_mcp_idempotency(
        tool_name="loop.snooze",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.update_loop(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until_utc},
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.snooze",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.enrich")
@with_db_init
@with_mcp_error_handling
def loop_enrich(loop_id: int, request_id: str | None = None) -> dict[str, Any]:
    settings = get_settings()

    payload = {"loop_id": loop_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.enrich",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        loop_service.request_enrichment(loop_id=loop_id, conn=conn)
        result = loop_enrichment.enrich_loop(loop_id=loop_id, conn=conn, settings=settings)

    _finalize_mcp_idempotency(
        tool_name="loop.enrich",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.create")
@with_db_init
@with_mcp_error_handling
def loop_view_create(
    name: str,
    query: str,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved view with a DSL query.

    Args:
        name: Unique view name
        query: DSL query string
        description: Optional description
        request_id: Optional idempotency key
    """
    settings = get_settings()
    payload = {"name": name, "query": query, "description": description}

    replay = _handle_mcp_idempotency(
        tool_name="loop.view.create",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.create_loop_view(
            name=name,
            query=query,
            description=description,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.view.create",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.list")
@with_db_init
@with_mcp_error_handling
def loop_view_list() -> list[dict[str, Any]]:
    """List all saved views."""
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.list_loop_views(conn=conn)


@mcp.tool(name="loop.view.get")
@with_db_init
@with_mcp_error_handling
def loop_view_get(view_id: int) -> dict[str, Any]:
    """Get a saved view by ID."""
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.get_loop_view(view_id=view_id, conn=conn)


@mcp.tool(name="loop.view.update")
@with_db_init
@with_mcp_error_handling
def loop_view_update(
    view_id: int,
    name: str | None = None,
    query: str | None = None,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update a saved view."""
    settings = get_settings()
    payload = {"view_id": view_id, "name": name, "query": query, "description": description}

    replay = _handle_mcp_idempotency(
        tool_name="loop.view.update",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        result = loop_service.update_loop_view(
            view_id=view_id,
            name=name,
            query=query,
            description=description,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.view.update",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.delete")
@with_db_init
@with_mcp_error_handling
def loop_view_delete(
    view_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete a saved view."""
    settings = get_settings()
    payload = {"view_id": view_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.view.delete",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        loop_service.delete_loop_view(view_id=view_id, conn=conn)

    result = {"deleted": True}
    _finalize_mcp_idempotency(
        tool_name="loop.view.delete",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


@mcp.tool(name="loop.view.apply")
@with_db_init
@with_mcp_error_handling
def loop_view_apply(
    view_id: int,
    limit: int = DEFAULT_LOOP_LIST_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Apply a saved view and return matching loops.

    Args:
        view_id: View ID to apply
        limit: Max results (default: 50)
        offset: Pagination offset (default: 0)

    Returns:
        Dict with view info and matching loops in 'items' key
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_service.apply_loop_view(
            view_id=view_id,
            limit=limit,
            offset=offset,
            conn=conn,
        )


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
