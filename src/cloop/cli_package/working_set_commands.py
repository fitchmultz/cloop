"""CLI handlers for working-set flows.

Purpose:
    Execute `cloop working-set *` commands by delegating to the shared
    working-set orchestration contract.

Responsibilities:
    - Map working-set domain errors to stable CLI exit codes
    - Parse CLI-only JSON arguments for metadata and bulk item payloads
    - Delegate working-set CRUD, context, membership, and undo to
      `loops/working_sets.py`
    - Reuse shared CLI runtime helpers for DB orchestration and rendering

Scope:
    - CLI execution for working-set commands only

Usage:
    - Imported by `cloop.cli_package.dispatch` for parsed-command routing

Invariants/Assumptions:
    - Exact event handles come from prior HTTP/CLI/MCP working-set responses
    - Invalid JSON inputs fail with stable CLI-facing validation errors
    - Exit code `1` represents validation or stale-handle failures

Non-scope:
    - Working-set business logic implementation
    - Output formatting implementation details
    - Transport-specific persistence rules
"""

from __future__ import annotations

import json
from argparse import Namespace
from typing import Any

from ..loops import working_sets
from ..loops._repo.shared import _UNSET
from ..loops.errors import ResourceNotFoundError, ValidationError, WorkingSetUndoNotPossibleError
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_db_action


def _common_error_handlers() -> list:
    return [
        error_handler(ValidationError, lambda exc: cli_error(exc.message)),
        error_handler(ResourceNotFoundError, lambda exc: cli_error(exc.message, exit_code=2)),
        error_handler(WorkingSetUndoNotPossibleError, lambda exc: cli_error(exc.message)),
    ]


def _load_json_object(raw: str | None, *, flag: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail_cli(f"invalid {flag} JSON: {exc.msg}")
    if not isinstance(value, dict):
        fail_cli(f"invalid {flag} JSON: expected an object")
    return value


def _load_json_array(raw: str, *, flag: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail_cli(f"invalid {flag} JSON: {exc.msg}")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        fail_cli(f"invalid {flag} JSON: expected an array of objects")
    return [dict(item) for item in value]


def working_set_list_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set list`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.list_working_sets(conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_get_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set get`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.get_working_set(working_set_id=args.id, conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_create_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set create`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.create_working_set(
            name=args.name,
            description=args.description,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_update_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set update`."""
    if args.description is not None and args.clear_description:
        fail_cli("provide --description or --clear-description, not both")
    if args.name is None and args.description is None and not args.clear_description:
        fail_cli("no fields to update")
    resolved_description = (
        None
        if args.clear_description
        else (_UNSET if args.description is None else args.description)
    )
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.update_working_set(
            working_set_id=args.id,
            name=args.name,
            description=resolved_description,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_delete_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set delete`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.delete_working_set(working_set_id=args.id, conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_context_get_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set context get`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.get_working_set_context(conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_context_update_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set context update`."""
    if args.active_working_set_id is not None and args.clear_active_working_set:
        fail_cli("provide --active-working-set-id or --clear-active-working-set, not both")
    active_working_set_id = None if args.clear_active_working_set else args.active_working_set_id
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.update_working_set_context(
            active_working_set_id=active_working_set_id,
            focus_mode_enabled=args.focus_mode == "on",
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_add_item_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set add-item`."""
    metadata = _load_json_object(args.metadata_json, flag="--metadata-json")
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.add_working_set_item(
            working_set_id=args.working_set,
            item_type=args.item_type,
            item_id=args.item_id,
            label=args.label,
            description=args.description,
            metadata=metadata,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_add_items_bulk_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set add-items-bulk`."""
    items = _load_json_array(args.items_json, flag="--items-json")
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.add_working_set_items_bulk(
            working_set_id=args.working_set,
            items=items,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_remove_item_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set remove-item`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.remove_working_set_item(
            working_set_id=args.working_set,
            item_id=args.item_id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_reorder_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set reorder`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.reorder_working_set_items(
            working_set_id=args.working_set,
            ordered_item_ids=args.ordered_item_ids,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def working_set_undo_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop working-set undo`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: working_sets.undo_working_set_event(
            expected_event_id=args.event_id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )
