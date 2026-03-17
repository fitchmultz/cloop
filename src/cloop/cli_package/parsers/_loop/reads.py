"""Loop read/search parser builders.

Purpose:
    Define the CLI parser builders for read-oriented loop commands.

Responsibilities:
    - Register `loop get`, `list`, `search`, and `semantic-search`
    - Keep read/query-oriented help text together
    - Preserve shared option names and formatter behavior

Scope:
    - Loop read/search parser construction only

Non-scope:
    - Query execution
    - Search ranking or pagination behavior

Usage:
    - Imported by `cloop.cli_package.parsers._loop`

Invariants/Assumptions:
    - Status-scope options use the shared `LOOP_STATUS_VALUES` helper text
    - Destination names remain stable for command dispatch
    - Formatting options are added through the shared parser helper
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from ..base import LOOP_STATUS_VALUES, add_format_option


def add_loop_read_parsers(loop_subparsers: Any) -> None:
    """Register all read/search-oriented loop parsers."""
    _add_get_parser(loop_subparsers)
    _add_list_parser(loop_subparsers)
    _add_search_parser(loop_subparsers)
    _add_semantic_search_parser(loop_subparsers)


def _add_get_parser(loop_subparsers: Any) -> None:
    """Add `loop get`."""
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
    """Add `loop list`."""
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
    """Add `loop search`."""
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
    """Add `loop semantic-search`."""
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
