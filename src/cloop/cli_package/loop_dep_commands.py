"""Loop dependency command handlers.

Purpose:
    Implement CLI command handlers for loop dependency operations.

Responsibilities:
    - Handle dep add, remove, list, and blocking commands
    - Normalize dependency command execution through the shared CLI runtime

Non-scope:
    - Timer operations
    - View operations
    - Core loop CRUD operations
"""

from __future__ import annotations

from argparse import Namespace

from ..loops.errors import DependencyCycleError, LoopNotFoundError
from ..loops.service import (
    add_loop_dependency,
    get_loop_blocking,
    get_loop_dependencies,
    remove_loop_dependency,
)
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_db_action


def _dependency_error_handlers() -> list:
    return [
        error_handler(
            LoopNotFoundError,
            lambda exc: cli_error(f"loop not found: {exc.loop_id}", exit_code=2),
        ),
        error_handler(
            DependencyCycleError,
            lambda exc: cli_error(exc.message),
        ),
    ]


def loop_dep_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop dep' commands."""
    action = args.dep_action

    if action == "add":
        if not args.loop_id or not args.depends_on:
            return run_cli_db_action(
                settings=settings,
                action=lambda _conn: fail_cli("--loop and --on required for add", exit_code=2),
            )
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: add_loop_dependency(
                loop_id=args.loop_id,
                depends_on_loop_id=args.depends_on,
                conn=conn,
            ),
            output_format=args.format,
            error_handlers=_dependency_error_handlers(),
        )

    if action == "remove":
        if not args.loop_id or not args.depends_on:
            return run_cli_db_action(
                settings=settings,
                action=lambda _conn: fail_cli("--loop and --on required for remove", exit_code=2),
            )
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: remove_loop_dependency(
                loop_id=args.loop_id,
                depends_on_loop_id=args.depends_on,
                conn=conn,
            ),
            output_format=args.format,
            error_handlers=_dependency_error_handlers(),
        )

    if action == "list":
        if not args.loop_id:
            return run_cli_db_action(
                settings=settings,
                action=lambda _conn: fail_cli("--loop required for list", exit_code=2),
            )
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: get_loop_dependencies(loop_id=args.loop_id, conn=conn),
            output_format=args.format,
            error_handlers=_dependency_error_handlers(),
        )

    if action == "blocking":
        if not args.loop_id:
            return run_cli_db_action(
                settings=settings,
                action=lambda _conn: fail_cli("--loop required for blocking", exit_code=2),
            )
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: get_loop_blocking(loop_id=args.loop_id, conn=conn),
            output_format=args.format,
            error_handlers=_dependency_error_handlers(),
        )

    return run_cli_db_action(
        settings=settings,
        action=lambda _conn: fail_cli(f"unknown dep action: {action}", exit_code=2),
    )
