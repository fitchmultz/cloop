"""Loop tool executors and definitions.

Purpose:
    Implement loop-management tools exposed through the public `cloop.tools` facade.

Responsibilities:
    - Execute loop capture, read, search, transition, close, snooze, and enrich flows
    - Centralize shared DB access and domain-to-tool error mapping for loop tools
    - Publish transport-neutral tool definitions for loop operations

Scope:
    - Loop tool execution and registration only

Non-scope:
    - Loop service/repository implementations
    - HTTP, CLI, or MCP transport orchestration

Usage:
    - Imported by the internal tool registry and re-exported by `cloop.tools`

Invariants/Assumptions:
    - Loop-facing validation errors stay stable for tool callers
    - Loop DB access flows through `cloop.db.core_connection`
    - Domain services remain the source of truth for loop behavior
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from .. import db
from ..loops import read_service
from ..loops.errors import (
    CloopError,
    LoopNotFoundError,
    TransitionError,
    ValidationError,
)
from ..loops.models import LoopStatus, format_utc_datetime, is_terminal_status, utc_now
from ..settings import get_settings
from .models import ToolDefinition

logger = logging.getLogger(__name__)


def _handle_tool_error(operation: str, exc: Exception) -> None:
    """Map shared infrastructure failures into stable tool-facing errors."""
    if isinstance(exc, CloopError):
        raise
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        raise ValidationError(operation, f"failed to {operation.replace('_', ' ')}: {exc}") from exc
    if isinstance(exc, sqlite3.Error):
        logger.error("Database error in %s: %s", operation, exc)
        raise ValidationError(operation, f"database error during {operation}: {exc}") from exc
    logger.exception("Unexpected error in %s: %s", operation, exc)
    raise ValidationError(operation, f"unexpected error during {operation}: {exc}") from exc


def _run_loop_db_action(
    operation: str,
    action: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Run a loop-domain action with shared connection and error handling."""
    settings = get_settings()
    try:
        with db.core_connection(settings) as conn:
            return action(conn=conn, settings=settings)
    except Exception as exc:
        _handle_tool_error(operation, exc)
    raise AssertionError("unreachable")


def _require_loop_id(kwargs: dict[str, Any], *, operation: str) -> int:
    """Extract and validate a loop id from tool kwargs."""
    loop_id = kwargs.get("loop_id")
    if loop_id is None:
        raise ValidationError("loop_id", f"required for {operation}")
    return int(loop_id)


def _parse_loop_status(
    raw_status: str | None,
    *,
    field: str = "status",
    required_for: str | None = None,
) -> LoopStatus:
    """Parse a loop status with tool-stable validation errors."""
    if not raw_status:
        if required_for is None:
            raise ValidationError(field, "status is required")
        raise ValidationError(field, f"required for {required_for}")
    try:
        return LoopStatus(raw_status)
    except ValueError as exc:
        raise ValidationError(field, f"invalid status: {raw_status}") from exc


def _map_loop_tool_errors(
    *,
    loop_id: int | None = None,
    wrap_field: str | None = None,
) -> Callable[[Exception], None]:
    """Build a mapper from loop-domain errors into tool-facing validation errors."""

    def _mapper(exc: Exception) -> None:
        if isinstance(exc, LoopNotFoundError):
            resolved_loop_id = loop_id if loop_id is not None else exc.loop_id
            raise ValidationError("loop_id", f"Loop not found: {resolved_loop_id}") from exc
        if isinstance(exc, TransitionError):
            raise ValidationError(
                "status",
                f"Invalid transition: {exc.from_status} -> {exc.to_status}",
            ) from exc
        if isinstance(exc, ValidationError):
            if wrap_field is None:
                raise
            raise ValidationError(wrap_field, str(exc)) from exc
        raise exc

    return _mapper


def _execute_loop_action(
    *,
    operation: str,
    action: Callable[..., dict[str, Any]],
    loop_id: int | None = None,
    wrap_field: str | None = None,
) -> dict[str, Any]:
    """Run a loop action with shared DB access and error mapping."""
    try:
        return _run_loop_db_action(operation, action)
    except Exception as exc:  # noqa: BLE001
        _map_loop_tool_errors(loop_id=loop_id, wrap_field=wrap_field)(exc)
        raise AssertionError("unreachable") from exc


def execute_loop_create(**kwargs: Any) -> dict[str, Any]:
    """Create a new loop."""
    from ..loops import service as loop_service

    raw_text = kwargs.get("raw_text")
    if not raw_text:
        raise ValidationError("raw_text", "required for loop_create")

    captured_at = kwargs.get("captured_at") or format_utc_datetime(utc_now())
    status = _parse_loop_status(kwargs.get("status", "inbox"))

    result = _execute_loop_action(
        operation="loop_create",
        action=lambda conn, settings: loop_service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=kwargs.get("client_tz_offset_min", 0),
            status=status,
            conn=conn,
        ),
    )
    return {"action": "loop_create", "loop": result}


def execute_loop_update(**kwargs: Any) -> dict[str, Any]:
    """Update one or more loop fields."""
    from ..loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_update")
    fields = kwargs.get("fields", {})
    if not fields:
        raise ValidationError("fields", "at least one field required")

    result = _execute_loop_action(
        operation="loop_update",
        loop_id=loop_id,
        action=lambda conn, settings: loop_service.update_loop(
            loop_id=loop_id,
            fields=fields,
            conn=conn,
        ),
    )
    return {"action": "loop_update", "loop": result}


def execute_loop_close(**kwargs: Any) -> dict[str, Any]:
    """Close a loop as completed or dropped."""
    from ..loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_close")
    status = _parse_loop_status(kwargs.get("status", "completed"))
    if status not in (LoopStatus.COMPLETED, LoopStatus.DROPPED):
        raise ValidationError("status", "must be 'completed' or 'dropped'")

    result = _execute_loop_action(
        operation="loop_close",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: loop_service.transition_status(
            loop_id=loop_id,
            to_status=status,
            note=kwargs.get("note"),
            conn=conn,
        ),
    )
    return {"action": "loop_close", "loop": result}


def execute_loop_list(**kwargs: Any) -> dict[str, Any]:
    """List loops with an optional status filter."""
    status_str = kwargs.get("status")
    status = _parse_loop_status(status_str) if status_str else None
    result = _execute_loop_action(
        operation="loop_list",
        action=lambda conn, settings: read_service.list_loops_page(
            status=status,
            limit=min(kwargs.get("limit", 50), 100),
            cursor=kwargs.get("cursor"),
            conn=conn,
        ),
    )
    return {"action": "loop_list", **result}


def execute_loop_search(**kwargs: Any) -> dict[str, Any]:
    """Search loops using the DSL query language."""
    result = _execute_loop_action(
        operation="loop_search",
        action=lambda conn, settings: read_service.search_loops_by_query_page(
            query=kwargs.get("query", ""),
            limit=min(kwargs.get("limit", 50), 100),
            cursor=kwargs.get("cursor"),
            conn=conn,
        ),
    )
    return {"action": "loop_search", **result}


def execute_loop_next(**kwargs: Any) -> dict[str, Any]:
    """Return prioritized next-action loop buckets."""
    result = _execute_loop_action(
        operation="loop_next",
        action=lambda conn, settings: read_service.next_loops(
            limit=min(kwargs.get("limit", 5), 20),
            conn=conn,
            settings=settings,
        ),
    )
    return {"action": "loop_next", **result}


def execute_loop_transition(**kwargs: Any) -> dict[str, Any]:
    """Transition a loop to a non-terminal status."""
    from ..loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_transition")
    status = _parse_loop_status(kwargs.get("status"), required_for="loop_transition")
    if is_terminal_status(status):
        raise ValidationError("status", "use loop_close for terminal statuses")

    result = _execute_loop_action(
        operation="loop_transition",
        loop_id=loop_id,
        action=lambda conn, settings: loop_service.transition_status(
            loop_id=loop_id,
            to_status=status,
            note=kwargs.get("note"),
            conn=conn,
        ),
    )
    return {"action": "loop_transition", "loop": result}


def execute_loop_snooze(**kwargs: Any) -> dict[str, Any]:
    """Snooze a loop until a future UTC timestamp."""
    from ..loops import service as loop_service

    loop_id = _require_loop_id(kwargs, operation="loop_snooze")
    snooze_until = kwargs.get("snooze_until_utc")
    if not snooze_until:
        raise ValidationError("snooze_until_utc", "required for loop_snooze")

    result = _execute_loop_action(
        operation="loop_snooze",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: loop_service.update_loop(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until},
            conn=conn,
        ),
    )
    return {"action": "loop_snooze", "loop": result}


def execute_loop_enrich(**kwargs: Any) -> dict[str, Any]:
    """Trigger synchronous enrichment for a loop."""
    from ..loops.enrichment_orchestration import orchestrate_loop_enrichment

    loop_id = _require_loop_id(kwargs, operation="loop_enrich")
    result = _execute_loop_action(
        operation="loop_enrich",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: orchestrate_loop_enrichment(
            loop_id=loop_id,
            conn=conn,
            settings=settings,
        ).to_payload(),
    )
    return {
        "action": "loop_enrich",
        "loop": result["loop"],
        "suggestion_id": result["suggestion_id"],
        "applied_fields": result.get("applied_fields", []),
        "needs_clarification": result.get("needs_clarification", []),
    }


def execute_loop_get(**kwargs: Any) -> dict[str, Any]:
    """Fetch one loop by id."""
    loop_id = _require_loop_id(kwargs, operation="loop_get")
    result = _execute_loop_action(
        operation="loop_get",
        loop_id=loop_id,
        wrap_field="fields",
        action=lambda conn, settings: read_service.get_loop(loop_id=loop_id, conn=conn),
    )
    return {"action": "loop_get", "loop": result}


LOOP_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="loop_create",
        description="Create a new loop/task. Use this to capture new items.",
        input_schema={
            "type": "object",
            "properties": {
                "raw_text": {
                    "type": "string",
                    "description": "The text content of the loop/task.",
                },
                "status": {
                    "type": "string",
                    "enum": ["inbox", "actionable", "blocked", "scheduled"],
                    "description": "Initial status (default: inbox).",
                },
                "captured_at": {
                    "type": "string",
                    "description": "ISO 8601 timestamp (optional, defaults to now).",
                },
                "client_tz_offset_min": {
                    "type": "integer",
                    "description": "Timezone offset in minutes (default: 0).",
                },
            },
            "required": ["raw_text"],
        },
        executor=execute_loop_create,
    ),
    ToolDefinition(
        name="loop_update",
        description="Update fields on an existing loop.",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {"type": "integer", "description": "ID of the loop to update."},
                "fields": {
                    "type": "object",
                    "description": "Fields to update.",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "next_action": {
                            "type": "string",
                            "description": "What to do next for this task.",
                        },
                        "due_at_utc": {
                            "type": "string",
                            "description": "Due date as ISO 8601 timestamp.",
                        },
                        "time_minutes": {
                            "type": "integer",
                            "description": "Estimated time in minutes.",
                        },
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["loop_id", "fields"],
        },
        executor=execute_loop_update,
    ),
    ToolDefinition(
        name="loop_close",
        description="Close a loop as completed or dropped. Use when a task is done.",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {"type": "integer", "description": "ID of the loop to close."},
                "status": {
                    "type": "string",
                    "enum": ["completed", "dropped"],
                    "description": "Terminal status (default: completed).",
                },
                "note": {
                    "type": "string",
                    "description": "Optional completion/drop note.",
                },
            },
            "required": ["loop_id"],
        },
        executor=execute_loop_close,
    ),
    ToolDefinition(
        name="loop_list",
        description="List loops with optional status filter. Use to show tasks.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [
                        "inbox",
                        "actionable",
                        "blocked",
                        "scheduled",
                        "completed",
                        "dropped",
                    ],
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50, max: 100).",
                },
                "cursor": {
                    "type": "string",
                    "description": "Pagination cursor from previous response.",
                },
            },
        },
        executor=execute_loop_list,
    ),
    ToolDefinition(
        name="loop_search",
        description="Search loops using query syntax. Supports status:value, tag:value.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g., 'status:inbox due:today').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50, max: 100).",
                },
                "cursor": {"type": "string", "description": "Pagination cursor."},
            },
            "required": ["query"],
        },
        executor=execute_loop_search,
    ),
    ToolDefinition(
        name="loop_next",
        description="Get prioritized next actions organized into buckets.",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max results per bucket (default: 5, max: 20).",
                }
            },
        },
        executor=execute_loop_next,
    ),
    ToolDefinition(
        name="loop_transition",
        description="Transition a loop to non-terminal status. Use loop_close.",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {"type": "integer", "description": "ID of the loop."},
                "status": {
                    "type": "string",
                    "enum": ["inbox", "actionable", "blocked", "scheduled"],
                    "description": "Target status.",
                },
                "note": {"type": "string", "description": "Optional transition note."},
            },
            "required": ["loop_id", "status"],
        },
        executor=execute_loop_transition,
    ),
    ToolDefinition(
        name="loop_snooze",
        description="Snooze a loop until a future time. Hidden from next actions.",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {
                    "type": "integer",
                    "description": "ID of the loop to snooze.",
                },
                "snooze_until_utc": {
                    "type": "string",
                    "description": "ISO 8601 timestamp when snooze expires.",
                },
            },
            "required": ["loop_id", "snooze_until_utc"],
        },
        executor=execute_loop_snooze,
    ),
    ToolDefinition(
        name="loop_enrich",
        description="Trigger AI enrichment for a loop. Extracts summary and tags.",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {
                    "type": "integer",
                    "description": "ID of the loop to enrich.",
                }
            },
            "required": ["loop_id"],
        },
        executor=execute_loop_enrich,
        agent_exposed=False,
    ),
    ToolDefinition(
        name="loop_get",
        description="Get a single loop by its ID. Retrieve full task details.",
        input_schema={
            "type": "object",
            "properties": {
                "loop_id": {
                    "type": "integer",
                    "description": "ID of the loop to retrieve.",
                }
            },
            "required": ["loop_id"],
        },
        executor=execute_loop_get,
    ),
)
