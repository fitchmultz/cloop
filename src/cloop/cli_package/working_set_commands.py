"""CLI handlers for working-set undo flows.

Purpose:
    Execute `cloop working-set *` commands by delegating to the shared
    working-set orchestration contract.

Responsibilities:
    - Map working-set undo domain errors to stable CLI exit codes
    - Delegate exact-handle working-set undo to `loops/working_sets.py`
    - Reuse shared CLI runtime helpers for DB orchestration and rendering

Scope:
    - CLI execution for working-set undo only

Usage:
    - Imported by `cloop.cli_package.dispatch` for parsed-command routing

Invariants/Assumptions:
    - Exact event handles come from prior HTTP/CLI/MCP working-set responses
    - Exit code `1` represents validation or stale-handle failures

Non-scope:
    - Working-set CRUD workflows outside undo
    - Output formatting implementation details
    - Transport-specific persistence rules
"""

from __future__ import annotations

from argparse import Namespace

from ..loops import working_sets
from ..loops.errors import ResourceNotFoundError, ValidationError, WorkingSetUndoNotPossibleError
from ..settings import Settings
from ._runtime import cli_error, error_handler, run_cli_db_action


def _common_error_handlers() -> list:
    return [
        error_handler(ValidationError, lambda exc: cli_error(exc.message)),
        error_handler(ResourceNotFoundError, lambda exc: cli_error(exc.message, exit_code=2)),
        error_handler(WorkingSetUndoNotPossibleError, lambda exc: cli_error(exc.message)),
    ]


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
