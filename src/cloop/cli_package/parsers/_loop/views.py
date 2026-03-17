"""Loop saved-view parser builders.

Purpose:
    Define the CLI parser builders for saved loop-view commands.

Responsibilities:
    - Register `loop view` subcommands
    - Keep saved-view help text together
    - Preserve stable destination names used by CLI dispatch

Scope:
    - Saved-view parser construction only

Non-scope:
    - Saved-view execution or persistence
    - DSL query evaluation behavior

Usage:
    - Imported by `cloop.cli_package.parsers._loop`

Invariants/Assumptions:
    - View subcommands use the `view_command` destination
    - Output-format flags are added through the shared parser helper
    - Saved-view argument names stay aligned with CLI command handlers
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from ..base import add_format_option


def add_view_parsers(loop_subparsers: Any) -> None:
    """Add all saved-view subcommand parsers."""
    view_parser = loop_subparsers.add_parser("view", help="Saved view operations")
    view_subparsers = view_parser.add_subparsers(dest="view_command", required=True)

    view_create_parser = view_subparsers.add_parser(
        "create",
        help="Create a saved view",
        description="Create a saved view with a DSL query",
        epilog="""
Examples:
  # Create a simple view
  cloop loop view create --name "Today's tasks" --query "status:open due:today"

  # Create with date range
  cloop loop view create --name "This week" --query "due:between:2026-02-20..2026-02-28"

  # Create with description
  cloop loop view create --name "Work items" --query "tag:work" --description "All work tasks"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    view_create_parser.add_argument("--name", required=True, help="View name")
    view_create_parser.add_argument("--query", required=True, help="DSL query string")
    view_create_parser.add_argument("--description", help="Optional description")
    add_format_option(view_create_parser)

    view_list_parser = view_subparsers.add_parser(
        "list",
        help="List saved views",
        description="List all saved views",
        epilog="""
Examples:
  # List views as JSON
  cloop loop view list

  # List views in table format
  cloop loop view list --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    add_format_option(view_list_parser)

    view_get_parser = view_subparsers.add_parser(
        "get",
        help="Get a saved view",
        description="Get details of a specific saved view",
        epilog="""
Examples:
  # Get view by ID
  cloop loop view get 1
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    view_get_parser.add_argument("id", type=int, help="View ID")
    add_format_option(view_get_parser)

    view_update_parser = view_subparsers.add_parser(
        "update",
        help="Update a saved view",
        description="Update an existing saved view",
        epilog="""
Examples:
  # Update view query
  cloop loop view update 1 --query "status:open tag:urgent"

  # Update name and description
  cloop loop view update 1 --name "Urgent work" --description "Urgent work items"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    view_update_parser.add_argument("id", type=int, help="View ID")
    view_update_parser.add_argument("--name", help="New view name")
    view_update_parser.add_argument("--query", help="New DSL query string")
    view_update_parser.add_argument("--description", help="New description")
    add_format_option(view_update_parser)

    view_delete_parser = view_subparsers.add_parser(
        "delete",
        help="Delete a saved view",
        description="Delete a saved view by ID",
        epilog="""
Examples:
  # Delete view by ID
  cloop loop view delete 1
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    view_delete_parser.add_argument("id", type=int, help="View ID")
    add_format_option(view_delete_parser)

    view_apply_parser = view_subparsers.add_parser(
        "apply",
        help="Apply a saved view",
        description="Execute a saved view query and return results",
        epilog="""
Examples:
  # Apply view and get results
  cloop loop view apply 1

  # Apply with custom limit
  cloop loop view apply 1 --limit 100
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    view_apply_parser.add_argument("id", type=int, help="View ID")
    view_apply_parser.add_argument("--limit", type=int, default=50, help="Max results")
    view_apply_parser.add_argument("--offset", type=int, default=0, help="Pagination offset")
    add_format_option(view_apply_parser)
