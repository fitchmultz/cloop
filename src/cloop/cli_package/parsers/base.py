"""Shared parser utilities for CLI.

Purpose:
    Common utilities used across parser modules.

Responsibilities:
    - Shared argument definitions
    - Parser helper functions
    - Common validation

Non-scope:
    - Does not define individual command parsers (in separate parser modules)
    - Does not execute CLI commands (handled by command handlers)
    - Does not manage application state or configuration
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

# Loop status values for help text
LOOP_STATUS_VALUES = ", ".join(
    ["open", "all", "inbox", "actionable", "blocked", "scheduled", "completed", "dropped"]
)


def add_format_option(parser: Any) -> None:
    """Add --format option to a parser."""
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="Output format (default: json)",
    )


def add_command_parser(
    subparsers: Any,
    name: str,
    *,
    help_text: str,
    description: str | None = None,
    examples: str | None = None,
    **kwargs: Any,
) -> Any:
    """Add a parser with the project's standard help/epilog formatting."""
    parser_kwargs: dict[str, Any] = {"help": help_text, **kwargs}
    if description is not None:
        parser_kwargs["description"] = description
    if examples is not None:
        parser_kwargs["epilog"] = examples
        parser_kwargs["formatter_class"] = RawDescriptionHelpFormatter
    return subparsers.add_parser(name, **parser_kwargs)
