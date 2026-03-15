"""CLI handlers for AI-native planning sessions.

Purpose:
    Execute `cloop plan session *` commands by delegating to the shared
    planning workflow contract.

Responsibilities:
    - Map planning workflow domain errors to stable CLI exit codes
    - Delegate planning session CRUD, refresh, movement, and execution to
      `loops/planning_workflows.py`

Non-scope:
    - Planning workflow business rules
    - Database lifecycle management outside the shared CLI runtime helper
    - Output formatting beyond choosing the requested renderer
"""

from __future__ import annotations

from argparse import Namespace

from ..loops import planning_workflows
from ..loops.errors import ResourceNotFoundError, ValidationError
from ..settings import Settings
from ._runtime import cli_error, error_handler, run_cli_db_action


def _common_error_handlers() -> list:
    return [
        error_handler(ValidationError, lambda exc: cli_error(exc.message)),
        error_handler(ResourceNotFoundError, lambda exc: cli_error(exc.message, exit_code=2)),
    ]


def planning_session_create_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: planning_workflows.create_planning_session(
            name=args.name,
            prompt=args.prompt,
            query=args.query,
            loop_limit=args.loop_limit,
            include_memory_context=args.include_memory_context,
            include_rag_context=args.include_rag_context,
            rag_k=args.rag_k,
            rag_scope=args.rag_scope,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def planning_session_list_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: planning_workflows.list_planning_sessions(conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def planning_session_get_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: planning_workflows.get_planning_session(
            session_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def planning_session_move_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: planning_workflows.move_planning_session(
            session_id=args.session,
            direction=args.direction,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def planning_session_refresh_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: planning_workflows.refresh_planning_session(
            session_id=args.session,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def planning_session_execute_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: planning_workflows.execute_planning_session_checkpoint(
            session_id=args.session,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def planning_session_delete_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: planning_workflows.delete_planning_session(
            session_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )
