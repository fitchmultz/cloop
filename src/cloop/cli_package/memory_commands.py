"""Memory command handlers.

Purpose:
    Implement CLI command handlers for direct memory-management workflows.

Responsibilities:
    - Route `cloop memory *` commands to the shared memory-management contract
    - Normalize CLI-facing JSON parsing and error handling
    - Reuse the shared CLI runtime for output and exit-code behavior

Non-scope:
    - Argument parsing (see parsers/memory.py)
    - Storage and domain validation logic (see memory_management.py)
"""

from __future__ import annotations

import json
from argparse import Namespace
from typing import Any

from .. import memory_management
from ..loops.errors import MemoryNotFoundError, ValidationError
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_db_action
from .output import emit_output


def _memory_error_handlers(entry_id: int | None = None) -> list:
    handlers = [
        error_handler(
            ValidationError,
            lambda exc: cli_error(exc.message),
        )
    ]
    if entry_id is not None:
        handlers.insert(
            0,
            error_handler(
                MemoryNotFoundError,
                lambda _exc: cli_error(f"memory {entry_id} not found", exit_code=2),
            ),
        )
    return handlers


def _parse_metadata_json(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail_cli(f"invalid --metadata-json value: {exc}")
    if not isinstance(parsed, dict):
        fail_cli("invalid --metadata-json value: expected a JSON object")
    return parsed


def _render_memory_query_result(result: dict[str, Any], output_format: str) -> None:
    if output_format == "table":
        emit_output(result.get("items", []), "table")
        return
    emit_output(result, output_format)


def memory_list_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop memory list`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: memory_management.list_memory_entries(
            category=args.category,
            source=args.source,
            min_priority=args.min_priority,
            limit=args.limit,
            cursor=args.cursor,
            settings=settings,
            conn=conn,
        ),
        render=lambda result: _render_memory_query_result(result, args.format),
        error_handlers=_memory_error_handlers(),
    )


def memory_search_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop memory search`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: memory_management.search_memory_entries(
            query=args.query,
            category=args.category,
            source=args.source,
            min_priority=args.min_priority,
            limit=args.limit,
            cursor=args.cursor,
            settings=settings,
            conn=conn,
        ),
        render=lambda result: _render_memory_query_result(result, args.format),
        error_handlers=_memory_error_handlers(),
    )


def memory_get_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop memory get`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: memory_management.get_memory_entry(
            entry_id=args.id,
            settings=settings,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_memory_error_handlers(args.id),
    )


def memory_create_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop memory create`."""
    metadata = _parse_metadata_json(args.metadata_json)
    payload = {
        "key": args.key,
        "content": args.content,
        "category": args.category,
        "priority": args.priority,
        "source": args.source,
    }
    if metadata is not None:
        payload["metadata"] = metadata

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: memory_management.create_memory_entry(
            payload=payload,
            settings=settings,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_memory_error_handlers(),
    )


def memory_update_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop memory update`."""
    metadata = _parse_metadata_json(args.metadata_json)
    fields: dict[str, Any] = {}
    if args.key is not None:
        fields["key"] = args.key
    if args.clear_key:
        fields["key"] = None
    if args.content is not None:
        fields["content"] = args.content
    if args.category is not None:
        fields["category"] = args.category
    if args.priority is not None:
        fields["priority"] = args.priority
    if args.source is not None:
        fields["source"] = args.source
    if metadata is not None:
        fields["metadata"] = metadata

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: memory_management.update_memory_entry(
            entry_id=args.id,
            fields=fields,
            settings=settings,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_memory_error_handlers(args.id),
    )


def memory_delete_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop memory delete`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: memory_management.delete_memory_entry(
            entry_id=args.id,
            settings=settings,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_memory_error_handlers(args.id),
    )
