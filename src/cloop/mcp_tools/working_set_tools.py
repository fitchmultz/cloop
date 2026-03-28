"""MCP tools for durable working-set workflows.

Purpose:
    Expose the working-set read, mutation, context, and exact-handle undo
    contracts to MCP clients through thin shared tool wrappers.

Responsibilities:
    - Register MCP tools for durable working-set listing, CRUD, membership, and
      focus-mode context updates
    - Reuse shared idempotency and error-handling helpers around
      `loops/working_sets.py`
    - Keep MCP docstrings aligned with the operator-facing working-set and undo
      contracts

Scope:
    - MCP transport wrappers for working-set operations only

Usage:
    - Registered by `cloop.mcp_server` through `cloop.mcp_tools`

Invariants/Assumptions:
    - Mutations reuse the shared working-set orchestration layer
    - Undo targets one exact latest reversible working-set event
    - MCP callers may safely retry mutations with the same `request_id`

Non-scope:
    - MCP server assembly
    - Working-set business logic implementation
    - Browser-only shell rendering
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping, TypeVar

from .. import db
from ..loops import working_sets
from ..loops._repo.shared import _UNSET
from ..loops.errors import ValidationError
from ..settings import get_settings
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_T = TypeVar("_T")


def _run_working_set_mutation(
    *,
    tool_name: str,
    request_id: str | None,
    payload: Mapping[str, Any],
    execute: Callable[[Any, Any], dict[str, Any]],
) -> dict[str, Any]:
    """Run one shared working-set MCP mutation with idempotency."""
    return run_idempotent_tool_mutation(
        tool_name=tool_name,
        request_id=request_id,
        payload=dict(payload),
        execute=execute,
    )


def _read_working_set(action: Callable[[Any], _T]) -> _T:
    """Run one read-only working-set action against the core database."""
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return action(conn)


@with_mcp_error_handling
def working_set_list() -> list[dict[str, Any]]:
    """List durable working sets.

    Use this to discover saved working-set sessions before opening or mutating
    one specific set.

    Returns:
        List of working-set payloads ordered by the shared service layer. Each
        item includes ordered items, launch metadata, and the latest reversible
        event handle when one exists.
    """
    return _read_working_set(lambda conn: working_sets.list_working_sets(conn=conn))


@with_mcp_error_handling
def working_set_get(working_set_id: int) -> dict[str, Any]:
    """Fetch one durable working set.

    Args:
        working_set_id: Working-set ID returned by `working_set.create`,
            `working_set.list`, or another working-set payload.

    Returns:
        Dict matching the shared `WorkingSetResponse` contract with ordered
        items, launch metadata, and latest reversible-event fields.

    Raises:
        ToolError: If the working set does not exist.
    """
    return _read_working_set(
        lambda conn: working_sets.get_working_set(working_set_id=working_set_id, conn=conn)
    )


@with_mcp_error_handling
def working_set_context_get() -> dict[str, Any]:
    """Fetch the active working-set and focus-mode context.

    Returns:
        Dict matching the shared `WorkingSetContextResponse` contract with the
        active working-set payload when one is selected.
    """
    return _read_working_set(lambda conn: working_sets.get_working_set_context(conn=conn))


@with_mcp_error_handling
def working_set_create(
    name: str,
    description: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create one durable working set.

    Args:
        name: Human-facing working-set name.
        description: Optional operator-facing description.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetResponse` contract.

    Examples:
        - Create a bounded launch queue and open it through its returned
          `launch` payload.
    """
    payload = {"name": name, "description": description}
    return _run_working_set_mutation(
        tool_name="working_set.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.create_working_set(
            name=name,
            description=description,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_update(
    working_set_id: int,
    name: str | None = None,
    description: str | None = None,
    clear_description: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update working-set metadata.

    Args:
        working_set_id: Working-set ID to update.
        name: Optional new working-set name.
        description: Optional new description value.
        clear_description: Clear the stored description when `true`.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetResponse` contract.

    Raises:
        ToolError: If no fields were supplied, both description modes were
            requested at once, or the working set is missing.
    """
    if name is None and description is None and not clear_description:
        raise ValidationError("working_set", "provide at least one field to update")
    if description is not None and clear_description:
        raise ValidationError(
            "description",
            "set description or clear_description, but not both",
        )
    payload = {
        "working_set_id": working_set_id,
        "name": name,
        "description": description,
        "clear_description": clear_description,
    }
    resolved_description = (
        None if clear_description else (_UNSET if description is None else description)
    )
    return _run_working_set_mutation(
        tool_name="working_set.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.update_working_set(
            working_set_id=working_set_id,
            name=name,
            description=resolved_description,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_delete(
    working_set_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete one durable working set.

    Args:
        working_set_id: Working-set ID to delete.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetDeleteResponse` contract including
        exact-handle undo metadata and refreshed context.
    """
    payload = {"working_set_id": working_set_id}
    return _run_working_set_mutation(
        tool_name="working_set.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.delete_working_set(
            working_set_id=working_set_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_context_update(
    focus_mode_enabled: bool,
    active_working_set_id: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Update the active working-set and focus-mode context.

    Args:
        focus_mode_enabled: Whether focus mode should be enabled after the
            update.
        active_working_set_id: Optional active working-set ID. Pass `null` to
            clear the active set while preserving the focus-mode flag.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetContextResponse` contract with the
        refreshed active context and latest reversible-event handle.
    """
    payload = {
        "focus_mode_enabled": focus_mode_enabled,
        "active_working_set_id": active_working_set_id,
    }
    return _run_working_set_mutation(
        tool_name="working_set.context.update",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.update_working_set_context(
            focus_mode_enabled=focus_mode_enabled,
            active_working_set_id=active_working_set_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_add_item(
    working_set_id: int,
    item_type: str,
    item_id: int | None = None,
    label: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add one item to a working set.

    Args:
        working_set_id: Working-set ID to update.
        item_type: Shared working-set item type (`loop`, `planning_session`,
            `relationship_review_session`, `enrichment_review_session`,
            `view`, `memory`, `query_anchor`, or `state_anchor`).
        item_id: Optional durable resource ID when the item type uses one.
        label: Optional override label.
        description: Optional override description.
        metadata: Optional launch metadata for query/state anchors.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetResponse` contract after the item is
        added.
    """
    payload = {
        "working_set_id": working_set_id,
        "item_type": item_type,
        "item_id": item_id,
        "label": label,
        "description": description,
        "metadata": metadata,
    }
    return _run_working_set_mutation(
        tool_name="working_set.add_item",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.add_working_set_item(
            working_set_id=working_set_id,
            item_type=item_type,
            item_id=item_id,
            label=label,
            description=description,
            metadata=metadata,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_add_items_bulk(
    working_set_id: int,
    items: list[dict[str, Any]],
    request_id: str | None = None,
) -> dict[str, Any]:
    """Add multiple items to a working set atomically.

    Args:
        working_set_id: Working-set ID to update.
        items: List of shared working-set item payloads.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetResponse` contract after the bulk
        add completes.
    """
    payload = {"working_set_id": working_set_id, "items": items}
    return _run_working_set_mutation(
        tool_name="working_set.add_items_bulk",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.add_working_set_items_bulk(
            working_set_id=working_set_id,
            items=items,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_remove_item(
    working_set_id: int,
    item_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Remove one working-set membership row.

    Args:
        working_set_id: Working-set ID to update.
        item_id: Membership-row ID returned in `WorkingSetResponse.items[*].id`.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetResponse` contract after the item is
        removed.
    """
    payload = {"working_set_id": working_set_id, "item_id": item_id}
    return _run_working_set_mutation(
        tool_name="working_set.remove_item",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.remove_working_set_item(
            working_set_id=working_set_id,
            item_id=item_id,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_reorder(
    working_set_id: int,
    ordered_item_ids: list[int],
    request_id: str | None = None,
) -> dict[str, Any]:
    """Rewrite working-set item order.

    Args:
        working_set_id: Working-set ID to reorder.
        ordered_item_ids: Complete ordered list of working-set item IDs.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict matching the shared `WorkingSetResponse` contract after reorder.
    """
    payload = {"working_set_id": working_set_id, "ordered_item_ids": ordered_item_ids}
    return _run_working_set_mutation(
        tool_name="working_set.reorder",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.reorder_working_set_items(
            working_set_id=working_set_id,
            ordered_item_ids=ordered_item_ids,
            conn=conn,
        ),
    )


@with_mcp_error_handling
def working_set_undo(
    expected_event_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Undo one exact latest working-set mutation event.

    Use this when a prior working-set response exposed
    `latest_reversible_event_id` and you want to reverse that exact mutation
    without guessing which event is latest. If a newer working-set change
    happened first, this tool fails with a stale-handle error instead of
    undoing the wrong state.

    Args:
        expected_event_id: Exact reversible working-set event ID returned by a
            previous working-set or working-set-context response.
        request_id: Optional idempotency key. Reusing the same key with the same
            arguments replays the original undo result.

    Returns:
        Dict with the shared working-set undo contract:
        - `working_set`: restored working-set payload when the undo targets a set
        - `context`: current working-set context payload after undo
        - `affected_working_set_id` / `affected_working_set_name`: primary set touched
        - `undone_event_id` / `undone_event_type`: event that was reversed
        - `undo_event_id`: audit event recorded for the undo mutation
        - `summary`: human-readable explanation of what changed
    """
    payload = {"expected_event_id": expected_event_id}
    return _run_working_set_mutation(
        tool_name="working_set.undo",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: working_sets.undo_working_set_event(
            expected_event_id=expected_event_id,
            conn=conn,
        ),
    )


def register_working_set_tools(mcp: "FastMCP") -> None:
    """Register working-set MCP tools."""
    from ._runtime import with_db_init

    mcp.tool(name="working_set.list")(with_db_init(working_set_list))
    mcp.tool(name="working_set.get")(with_db_init(working_set_get))
    mcp.tool(name="working_set.context.get")(with_db_init(working_set_context_get))
    mcp.tool(name="working_set.context.update")(with_db_init(working_set_context_update))
    mcp.tool(name="working_set.create")(with_db_init(working_set_create))
    mcp.tool(name="working_set.update")(with_db_init(working_set_update))
    mcp.tool(name="working_set.delete")(with_db_init(working_set_delete))
    mcp.tool(name="working_set.add_item")(with_db_init(working_set_add_item))
    mcp.tool(name="working_set.add_items_bulk")(with_db_init(working_set_add_items_bulk))
    mcp.tool(name="working_set.remove_item")(with_db_init(working_set_remove_item))
    mcp.tool(name="working_set.reorder")(with_db_init(working_set_reorder))
    mcp.tool(name="working_set.undo")(with_db_init(working_set_undo))
