"""Loop bulk-operation parser builders.

Purpose:
    Define the CLI parser builders for query-driven bulk loop operations.

Responsibilities:
    - Register `loop bulk` subcommands
    - Keep bulk-operation help text and shared options together
    - Preserve stable destination names used by CLI dispatch

Scope:
    - Bulk parser construction only

Non-scope:
    - Bulk command execution
    - Query/mutation business rules

Usage:
    - Imported by `cloop.cli_package.parsers._loop`

Invariants/Assumptions:
    - Bulk subcommands use the `bulk_action` destination
    - Confirmation and dry-run flags keep their established destinations
    - Format flags are added uniformly through the shared parser helper
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from ..base import add_format_option


def add_bulk_parser(loop_subparsers: Any) -> None:
    """Add `loop bulk` and its subcommands."""
    bulk_parser = loop_subparsers.add_parser(
        "bulk",
        help="Bulk operations on query-selected loops",
        description="Perform bulk operations on loops selected by DSL query",
        epilog="""
Examples:
  # Preview closing all inbox items tagged 'old' (dry-run)
  cloop loop bulk close --query "status:inbox tag:old" --dry-run

  # Close all matched loops
  cloop loop bulk close --query "status:inbox tag:old"

  # Update project on matched loops
  cloop loop bulk update --query "tag:client-a" --project "ClientA"

  # Snooze matched loops until tomorrow
  cloop loop bulk snooze --query "status:scheduled" --until "1d"

  # Re-enrich the current open backlog
  cloop loop bulk enrich --query "status:open"

  # Transactional mode (rollback on any failure)
  cloop loop bulk close --query "status:inbox" --transactional

  # Limit affected loops
  cloop loop bulk close --query "status:inbox" --limit 50
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    bulk_subparsers = bulk_parser.add_subparsers(dest="bulk_action", required=True)

    _add_bulk_update_parser(bulk_subparsers)
    _add_bulk_close_parser(bulk_subparsers)
    _add_bulk_snooze_parser(bulk_subparsers)
    _add_bulk_enrich_parser(bulk_subparsers)


def _add_bulk_update_parser(bulk_subparsers: Any) -> None:
    """Add `loop bulk update`."""
    update_parser = bulk_subparsers.add_parser(
        "update",
        help="Bulk update matched loops",
        description="Update fields on loops matching DSL query",
    )
    update_parser.add_argument(
        "--query",
        "-q",
        required=True,
        help="DSL query to select target loops",
    )
    update_parser.add_argument("--title", help="Set title")
    update_parser.add_argument("--project", help="Set project name")
    update_parser.add_argument(
        "--tags",
        help="Set comma-separated tags (replaces existing)",
    )
    update_parser.add_argument("--urgency", type=float, help="Set urgency (0.0-1.0)")
    update_parser.add_argument("--importance", type=float, help="Set importance (0.0-1.0)")
    update_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview targets without applying changes",
    )
    update_parser.add_argument(
        "--transactional",
        action="store_true",
        help="Rollback all on any failure",
    )
    update_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max loops to affect (default: 100)",
    )
    update_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        dest="confirm",
        help="Skip confirmation prompt",
    )
    add_format_option(update_parser)


def _add_bulk_close_parser(bulk_subparsers: Any) -> None:
    """Add `loop bulk close`."""
    close_parser = bulk_subparsers.add_parser(
        "close",
        help="Bulk close matched loops",
        description="Close loops matching DSL query",
    )
    close_parser.add_argument(
        "--query",
        "-q",
        required=True,
        help="DSL query to select target loops",
    )
    close_parser.add_argument(
        "--dropped",
        action="store_true",
        help="Close as dropped instead of completed",
    )
    close_parser.add_argument("--note", help="Completion/drop note")
    close_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview targets without applying changes",
    )
    close_parser.add_argument(
        "--transactional",
        action="store_true",
        help="Rollback all on any failure",
    )
    close_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max loops to affect (default: 100)",
    )
    close_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        dest="confirm",
        help="Skip confirmation prompt",
    )
    add_format_option(close_parser)


def _add_bulk_snooze_parser(bulk_subparsers: Any) -> None:
    """Add `loop bulk snooze`."""
    snooze_parser = bulk_subparsers.add_parser(
        "snooze",
        help="Bulk snooze matched loops",
        description="Snooze loops matching DSL query",
    )
    snooze_parser.add_argument(
        "--query",
        "-q",
        required=True,
        help="DSL query to select target loops",
    )
    snooze_parser.add_argument(
        "--until",
        required=True,
        help="Duration (30m, 1h, 2d) or ISO8601 timestamp",
    )
    snooze_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview targets without applying changes",
    )
    snooze_parser.add_argument(
        "--transactional",
        action="store_true",
        help="Rollback all on any failure",
    )
    snooze_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max loops to affect (default: 100)",
    )
    snooze_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        dest="confirm",
        help="Skip confirmation prompt",
    )
    add_format_option(snooze_parser)


def _add_bulk_enrich_parser(bulk_subparsers: Any) -> None:
    """Add `loop bulk enrich`."""
    enrich_parser = bulk_subparsers.add_parser(
        "enrich",
        help="Bulk enrich matched loops",
        description="Run explicit AI enrichment across loops matching a DSL query",
    )
    enrich_parser.add_argument(
        "--query",
        "-q",
        required=True,
        help="DSL query to select target loops",
    )
    enrich_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview targets without applying changes",
    )
    enrich_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max loops to affect (default: 100)",
    )
    enrich_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        dest="confirm",
        help="Skip confirmation prompt",
    )
    add_format_option(enrich_parser)
