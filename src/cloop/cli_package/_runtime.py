"""Shared CLI command runtime helpers.

Purpose:
    Centralize the common orchestration concerns for CLI command handlers so
    loop-related commands follow one contract for database access, expected
    error handling, output emission, and exit-code behavior.

Responsibilities:
    - Wrap command execution with consistent expected-error mapping
    - Manage shared database connection setup for DB-backed commands
    - Emit structured output or delegated text rendering
    - Provide explicit CLI-facing command errors with exit codes

Non-scope:
    - Argument parsing
    - Business logic and service-layer orchestration
    - Formatting the contents of domain-specific text renderers

Usage:
    - Use `run_cli_action(...)` for commands that do not need a database
      connection.
    - Use `run_cli_db_action(...)` for commands that execute inside
      `db.core_connection(settings)`.

Invariants/Assumptions:
    - Unexpected exceptions should propagate instead of being silently collapsed
      into generic exit codes.
    - Expected user/domain/database failures should be mapped explicitly.
    - Structured output defaults to `emit_output(...)` when an output format is
      supplied.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from .. import db
from ..settings import Settings
from .output import emit_output

ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class CliCommandError(Exception):
    """A handled CLI failure with a user-facing message and exit code."""

    message: str
    exit_code: int = 1


@dataclass(frozen=True, slots=True)
class ErrorHandler:
    """Mapping from an expected exception type to a CLI-facing failure."""

    exception_types: tuple[type[BaseException], ...]
    transform: Callable[[BaseException], CliCommandError]

    def matches(self, exc: BaseException) -> bool:
        """Return whether this handler applies to the provided exception."""
        return isinstance(exc, self.exception_types)


def cli_error(message: str, *, exit_code: int = 1) -> CliCommandError:
    """Create a CLI-facing command failure."""
    return CliCommandError(message=message, exit_code=exit_code)


def fail_cli(message: str, *, exit_code: int = 1) -> NoReturn:
    """Raise a handled CLI-facing command failure."""
    raise cli_error(message, exit_code=exit_code)


def error_handler(
    exception_types: type[BaseException] | tuple[type[BaseException], ...],
    transform: Callable[[BaseException], CliCommandError],
) -> ErrorHandler:
    """Create a typed CLI error handler."""
    normalized = exception_types if isinstance(exception_types, tuple) else (exception_types,)
    return ErrorHandler(exception_types=normalized, transform=transform)


def sqlite_error_handler() -> ErrorHandler:
    """Build the standard database-error handler."""
    return error_handler(
        sqlite3.Error,
        lambda exc: cli_error(f"database error - {exc}"),
    )


def emit_cli_error(message: str) -> None:
    """Emit a standardized CLI error message to stderr."""
    print(f"error: {message}", file=sys.stderr)


def run_cli_action(
    *,
    action: Callable[[], ResultT],
    output_format: str | None = None,
    render: Callable[[ResultT], None] | None = None,
    error_handlers: list[ErrorHandler] | None = None,
    success_exit_code: int = 0,
) -> int:
    """Run a CLI action with shared error mapping and output handling."""
    try:
        result = action()
    except CliCommandError as exc:
        emit_cli_error(exc.message)
        return exc.exit_code
    except BaseException as exc:  # noqa: BLE001
        for handler in error_handlers or []:
            if handler.matches(exc):
                mapped = handler.transform(exc)
                emit_cli_error(mapped.message)
                return mapped.exit_code
        raise

    if render is not None:
        render(result)
    elif output_format is not None:
        emit_output(result, output_format)
    return success_exit_code


def run_cli_db_action(
    *,
    settings: Settings,
    action: Callable[[sqlite3.Connection], ResultT],
    output_format: str | None = None,
    render: Callable[[ResultT], None] | None = None,
    error_handlers: list[ErrorHandler] | None = None,
    success_exit_code: int = 0,
) -> int:
    """Run a DB-backed CLI action with shared connection and error handling."""

    def _execute() -> ResultT:
        with db.core_connection(settings) as conn:
            return action(conn)

    handlers = [*(error_handlers or []), sqlite_error_handler()]
    return run_cli_action(
        action=_execute,
        output_format=output_format,
        render=render,
        error_handlers=handlers,
        success_exit_code=success_exit_code,
    )
