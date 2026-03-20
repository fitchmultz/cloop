"""Working-set command argument parsers.

Purpose:
    Define the `cloop working-set` CLI surface for durable working-set undo.

Responsibilities:
    - Add working-set parser trees for deterministic undo flows
    - Document exact-handle working-set undo usage in CLI help text
    - Keep parser options aligned with the shared working-set undo contract

Scope:
    - Argparse parser creation for top-level working-set commands only

Usage:
    - Imported by `cloop.cli_package.parser_factory` when building the full CLI

Invariants/Assumptions:
    - `expected_event_id` must be supplied explicitly by the caller
    - Parser help text should match the shared working-set undo behavior

Non-scope:
    - Working-set business logic execution
    - Database lifecycle management
    - Output rendering beyond parser-level format selection
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from .base import add_format_option


def add_working_set_parser(subparsers: Any) -> None:
    """Add the top-level `working-set` parser."""
    parser = subparsers.add_parser(
        "working-set",
        help="Working-set continuity and undo commands",
    )
    working_set_subparsers = parser.add_subparsers(dest="working_set_command", required=True)

    undo = working_set_subparsers.add_parser(
        "undo",
        help="Undo one exact latest working-set mutation event",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set undo --event-id 42
  cloop working-set undo --event-id 42 --format table

Exit codes:
  0  success
  1  validation/input error
  2  resource not found
        """,
    )
    undo.add_argument(
        "--event-id",
        type=int,
        required=True,
        help="Exact working-set event ID to undo",
    )
    add_format_option(undo)
