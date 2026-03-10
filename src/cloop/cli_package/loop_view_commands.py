"""Loop view command handlers.

Purpose:
    Implement CLI command handlers for loop view operations.

Responsibilities:
    - Handle view create, list, get, update, delete, and apply commands
    - Route DB access, error mapping, and output through the shared CLI runtime

Non-scope:
    - Loop data operations (see loop_core_commands.py)
    - Dependency operations (see loop_dep_commands.py)
    - Timer operations (see loop_timer_commands.py)
"""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from ..loops.errors import ValidationError
from ..loops.views import (
    apply_loop_view,
    create_loop_view,
    delete_loop_view,
    get_loop_view,
    list_loop_views,
    update_loop_view,
)
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_db_action


def _validation_error_handler() -> list:
    return [
        error_handler(
            ValidationError,
            lambda exc: cli_error(exc.message),
        )
    ]


def loop_view_create_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view create' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: create_loop_view(
            name=args.name,
            query=args.query,
            description=args.description,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_validation_error_handler(),
    )


def loop_view_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view list' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: list_loop_views(conn=conn),
        output_format=args.format,
    )


def loop_view_get_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view get' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: get_loop_view(view_id=args.id, conn=conn),
        output_format=args.format,
        error_handlers=_validation_error_handler(),
    )


def loop_view_update_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view update' command."""
    fields: dict[str, Any] = {}
    if args.name is not None:
        fields["name"] = args.name
    if args.query is not None:
        fields["query"] = args.query
    if args.description is not None:
        fields["description"] = args.description

    if not fields:
        return run_cli_db_action(
            settings=settings,
            action=lambda _conn: fail_cli("no fields to update"),
        )

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: update_loop_view(view_id=args.id, conn=conn, **fields),
        output_format=args.format,
        error_handlers=_validation_error_handler(),
    )


def loop_view_delete_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view delete' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: (
            delete_loop_view(view_id=args.id, conn=conn),
            {"deleted": True},
        )[1],
        output_format=args.format,
        error_handlers=_validation_error_handler(),
    )


def loop_view_apply_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view apply' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: apply_loop_view(
            view_id=args.id,
            limit=args.limit,
            offset=args.offset,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_validation_error_handler(),
    )
