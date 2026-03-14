"""Loop command argument parsers.

Purpose:
    Argument parsers for loop lifecycle commands.

Responsibilities:
    - Define argument parsers for loop subcommands (get, list, search,
      semantic-search, update, status, close, enrich, snooze)
    - Define argument parsers for view subcommands (create, list, get, update,
      delete, apply)
    - Define argument parsers for dependency subcommands (add, remove, list,
      blocking)
    - Wire together claim, timer, and misc parsers via delegation

Non-scope:
    - Does not handle argument parsing for capture, inbox, next commands
      (see loop_misc_parsers.py)
    - Does not handle argument parsing for claim or timer commands
      (delegates to loop_claim_parsers.py and loop_timer_parsers.py)
    - Does not execute commands or interact with the database
"""

from __future__ import annotations

from typing import Any

from .base import LOOP_STATUS_VALUES, add_format_option


def add_loop_parser(subparsers: Any) -> None:
    """Add 'loop' command and all subcommand parsers."""

    from .loop_claim_parsers import add_claim_parsers
    from .loop_misc_parsers import add_misc_loop_parsers
    from .loop_timer_parsers import add_sessions_parser, add_timer_parser

    loop_parser = subparsers.add_parser("loop", help="Loop lifecycle commands")
    loop_subparsers = loop_parser.add_subparsers(dest="loop_command", required=True)

    # Core loop parsers
    _add_get_parser(loop_subparsers)
    _add_list_parser(loop_subparsers)
    _add_search_parser(loop_subparsers)
    _add_semantic_search_parser(loop_subparsers)
    _add_update_parser(loop_subparsers)
    _add_status_parser(loop_subparsers)
    _add_close_parser(loop_subparsers)
    _add_enrich_parser(loop_subparsers)
    _add_snooze_parser(loop_subparsers)
    _add_view_parsers(loop_subparsers)
    _add_dep_parsers(loop_subparsers)

    # Bulk parsers
    _add_bulk_parser(loop_subparsers)

    # Claim parsers
    add_claim_parsers(loop_subparsers)

    # Timer parsers
    add_timer_parser(loop_subparsers)
    add_sessions_parser(loop_subparsers)

    # Misc parsers (review, events, undo, metrics)
    add_misc_loop_parsers(loop_subparsers)


def _add_get_parser(loop_subparsers: Any) -> None:
    """Add 'loop get' parser."""
    from argparse import RawDescriptionHelpFormatter

    get_parser = loop_subparsers.add_parser(
        "get",
        help="Get a loop by ID",
        description="Retrieve detailed information about a specific loop",
        epilog="""
Examples:
  # Get loop by ID as JSON
  cloop loop get 123

  # Get loop in table format
  cloop loop get 123 --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    get_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(get_parser)


def _add_list_parser(loop_subparsers: Any) -> None:
    """Add 'loop list' parser."""
    from argparse import RawDescriptionHelpFormatter

    list_parser = loop_subparsers.add_parser(
        "list",
        help="List loops",
        description="List loops with optional filtering by status or tag",
        epilog="""
Examples:
  # List all open loops (default)
  cloop loop list

  # List inbox items
  cloop loop list --status inbox

  # List completed loops
  cloop loop list --status completed

  # List loops with specific tag
  cloop loop list --tag work --format table

  # List all loops (no filter)
  cloop loop list --status all --limit 100
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    list_parser.add_argument(
        "--status",
        default="open",
        help=f"Filter by status ({LOOP_STATUS_VALUES})",
    )
    list_parser.add_argument("--tag", help="Filter by tag")
    list_parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    list_parser.add_argument("--offset", type=int, default=0, help="Pagination offset (default: 0)")
    add_format_option(list_parser)


def _add_search_parser(loop_subparsers: Any) -> None:
    """Add 'loop search' parser."""
    from argparse import RawDescriptionHelpFormatter

    search_parser = loop_subparsers.add_parser(
        "search",
        help="Search loops with DSL query",
        description="Search loops using query DSL (status:, tag:, due:, full-text)",
        epilog="""
Examples:
  # Full-text search
  cloop loop search "groceries"

  # DSL: status and tag
  cloop loop search "status:inbox tag:work"

  # DSL: due today
  cloop loop search "status:open due:today"

  # DSL: due on specific date
  cloop loop search "due:on:2026-02-25"

  # DSL: due in date range
  cloop loop search "due:between:2026-02-20..2026-02-28"

  # DSL: blocked items
  cloop loop search "blocked"

  # DSL: project filter
  cloop loop search "project:ClientAlpha"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    search_parser.add_argument("query", nargs="?", help="DSL query string")
    search_parser.add_argument("--query", dest="query_flag", help="DSL query string")
    search_parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    search_parser.add_argument(
        "--offset", type=int, default=0, help="Pagination offset (default: 0)"
    )
    add_format_option(search_parser)


def _add_semantic_search_parser(loop_subparsers: Any) -> None:
    """Add 'loop semantic-search' parser."""
    from argparse import RawDescriptionHelpFormatter

    search_parser = loop_subparsers.add_parser(
        "semantic-search",
        help="Search loops by semantic similarity",
        description="Search loops by natural-language meaning instead of DSL term matching",
        epilog="""
Examples:
  # Find loops about groceries, even if wording differs
  cloop loop semantic-search "buy milk and eggs"

  # Limit to inbox items only
  cloop loop semantic-search "customer follow-up" --status inbox

  # Filter out weak matches
  cloop loop semantic-search "quarterly planning" --min-score 0.4 --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    search_parser.add_argument("query", nargs="?", help="Natural-language semantic query")
    search_parser.add_argument("--query", dest="query_flag", help="Natural-language semantic query")
    search_parser.add_argument(
        "--status",
        default="open",
        help=f"Filter by status scope ({LOOP_STATUS_VALUES})",
    )
    search_parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    search_parser.add_argument(
        "--offset", type=int, default=0, help="Pagination offset (default: 0)"
    )
    search_parser.add_argument(
        "--min-score",
        dest="min_score",
        type=float,
        help="Optional minimum similarity score between 0.0 and 1.0",
    )
    add_format_option(search_parser)


def _add_update_parser(loop_subparsers: Any) -> None:
    """Add 'loop update' parser."""
    from argparse import RawDescriptionHelpFormatter

    update_parser = loop_subparsers.add_parser(
        "update",
        help="Update loop fields",
        description="Update one or more fields on a loop",
        epilog="""
Examples:
  # Set next action
  cloop loop update 1 --next-action "Call client"

  # Set due date
  cloop loop update 1 --due-at "2026-02-20T17:00:00Z"

  # Set tags (replaces existing)
  cloop loop update 1 --tags "work,urgent"

  # Multiple fields at once
  cloop loop update 1 --title "Updated title" --urgency 0.8 --importance 0.9
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    update_parser.add_argument("id", type=int, help="Loop ID")
    update_parser.add_argument("--title", help="Update title")
    update_parser.add_argument("--summary", help="Update summary")
    update_parser.add_argument("--next-action", dest="next_action", help="Update next action")
    update_parser.add_argument("--due-at", dest="due_at", help="Update due date (ISO8601)")
    update_parser.add_argument(
        "--snooze-until", dest="snooze_until", help="Update snooze time (ISO8601)"
    )
    update_parser.add_argument(
        "--time-minutes", dest="time_minutes", type=int, help="Estimated time"
    )
    update_parser.add_argument(
        "--activation-energy",
        dest="activation_energy",
        type=int,
        choices=[0, 1, 2, 3],
        help="Activation energy (0-3)",
    )
    update_parser.add_argument("--urgency", type=float, help="Urgency (0.0-1.0)")
    update_parser.add_argument("--importance", type=float, help="Importance (0.0-1.0)")
    update_parser.add_argument("--project", help="Project name")
    update_parser.add_argument(
        "--blocked-reason", dest="blocked_reason", help="Reason for blocked status"
    )
    update_parser.add_argument(
        "--tags",
        help="Comma-separated tags (clears existing tags, use empty string to clear all)",
    )
    update_parser.add_argument(
        "--claim-token", dest="claim_token", help="Claim token for claimed loops"
    )
    add_format_option(update_parser)


def _add_status_parser(loop_subparsers: Any) -> None:
    """Add 'loop status' parser."""
    from argparse import RawDescriptionHelpFormatter

    status_parser = loop_subparsers.add_parser(
        "status",
        help="Transition loop status",
        description="Transition a loop to a new status",
        epilog="""
Examples:
  # Move to actionable
  cloop loop status 1 actionable

  # Move to scheduled
  cloop loop status 1 scheduled

  # Move to blocked
  cloop loop status 1 blocked

  # With claim token for claimed loop
  cloop loop status 1 actionable --claim-token TOKEN
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    status_parser.add_argument("id", type=int, help="Loop ID")
    status_parser.add_argument(
        "status",
        help="Target status (inbox, actionable, blocked, scheduled, completed, dropped)",
    )
    status_parser.add_argument(
        "--note",
        help="Optional note (used for completion_note when completing)",
    )
    status_parser.add_argument(
        "--claim-token", dest="claim_token", help="Claim token for claimed loops"
    )
    add_format_option(status_parser)


def _add_close_parser(loop_subparsers: Any) -> None:
    """Add 'loop close' parser."""
    from argparse import RawDescriptionHelpFormatter

    close_parser = loop_subparsers.add_parser(
        "close",
        help="Close a loop",
        description="Close a loop as completed or dropped",
        epilog="""
Examples:
  # Close as completed
  cloop loop close 1

  # Close as dropped
  cloop loop close 1 --dropped

  # With completion note
  cloop loop close 1 --note "Finished ahead of schedule"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    close_parser.add_argument("id", type=int, help="Loop ID")
    close_parser.add_argument(
        "--dropped",
        action="store_true",
        help="Close as dropped instead of completed",
    )
    close_parser.add_argument("--note", help="Completion/drop note")
    close_parser.add_argument(
        "--claim-token", dest="claim_token", help="Claim token for claimed loops"
    )
    add_format_option(close_parser)


def _add_enrich_parser(loop_subparsers: Any) -> None:
    """Add 'loop enrich' parser."""
    enrich_parser = loop_subparsers.add_parser(
        "enrich",
        help="Run AI enrichment for a loop",
    )
    enrich_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(enrich_parser)


def _add_snooze_parser(loop_subparsers: Any) -> None:
    """Add 'loop snooze' parser."""
    from argparse import RawDescriptionHelpFormatter

    snooze_parser = loop_subparsers.add_parser(
        "snooze",
        help="Snooze a loop",
        description="Temporarily hide a loop until a future time",
        epilog="""
Examples:
  # Snooze for 30 minutes
  cloop loop snooze 1 30m

  # Snooze for 2 hours
  cloop loop snooze 1 2h

  # Snooze for 3 days
  cloop loop snooze 1 3d

  # Snooze until specific time
  cloop loop snooze 1 "2026-02-20T09:00:00Z"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    snooze_parser.add_argument("id", type=int, help="Loop ID")
    snooze_parser.add_argument(
        "duration",
        help="Duration (30m, 1h, 2d, 1w) or ISO8601 timestamp",
    )
    add_format_option(snooze_parser)


def _add_view_parsers(loop_subparsers: Any) -> None:
    """Add all view subcommand parsers."""
    from argparse import RawDescriptionHelpFormatter

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


def _add_dep_parsers(loop_subparsers: Any) -> None:
    """Add all dependency subcommand parsers."""
    from argparse import RawDescriptionHelpFormatter

    dep_parser = loop_subparsers.add_parser("dep", help="Manage loop dependencies")
    dep_subparsers = dep_parser.add_subparsers(dest="dep_action", required=True)

    dep_add_parser = dep_subparsers.add_parser(
        "add",
        help="Add a dependency",
        description="Add a dependency between loops (loop depends on another)",
        epilog="""
Examples:
  # Make loop 123 depend on loop 456
  cloop loop dep add --loop 123 --on 456
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    dep_add_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    dep_add_parser.add_argument(
        "--on", "-o", type=int, dest="depends_on", required=True, help="Depends on loop ID"
    )
    add_format_option(dep_add_parser)

    dep_remove_parser = dep_subparsers.add_parser(
        "remove",
        help="Remove a dependency",
        description="Remove a dependency relationship between loops",
        epilog="""
Examples:
  # Remove dependency: loop 123 no longer depends on loop 456
  cloop loop dep remove --loop 123 --on 456
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    dep_remove_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    dep_remove_parser.add_argument(
        "--on", "-o", type=int, dest="depends_on", required=True, help="Depends on loop ID"
    )
    add_format_option(dep_remove_parser)

    dep_list_parser = dep_subparsers.add_parser(
        "list",
        help="List dependencies",
        description="List all loops that this loop depends on (blockers)",
        epilog="""
Examples:
  # List dependencies for loop 123
  cloop loop dep list --loop 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    dep_list_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    add_format_option(dep_list_parser)

    dep_blocking_parser = dep_subparsers.add_parser(
        "blocking",
        help="List what this loop blocks",
        description="List all loops that are blocked by this loop (dependents)",
        epilog="""
Examples:
  # List loops blocked by loop 123
  cloop loop dep blocking --loop 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    dep_blocking_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    add_format_option(dep_blocking_parser)


def _add_bulk_parser(loop_subparsers: Any) -> None:
    """Add 'loop bulk' parser."""
    from argparse import RawDescriptionHelpFormatter

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

  # Transactional mode (rollback on any failure)
  cloop loop bulk close --query "status:inbox" --transactional

  # Limit affected loops
  cloop loop bulk close --query "status:inbox" --limit 50
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    bulk_subparsers = bulk_parser.add_subparsers(dest="bulk_action", required=True)

    # bulk update
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
    update_parser.add_argument(
        "--urgency",
        type=float,
        help="Set urgency (0.0-1.0)",
    )
    update_parser.add_argument(
        "--importance",
        type=float,
        help="Set importance (0.0-1.0)",
    )
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

    # bulk close
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

    # bulk snooze
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
