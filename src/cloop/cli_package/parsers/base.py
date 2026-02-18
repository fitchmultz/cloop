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
