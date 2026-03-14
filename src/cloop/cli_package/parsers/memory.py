"""Memory command parsers.

Purpose:
    Define the CLI surface for direct memory-management workflows.

Responsibilities:
    - Add the top-level `memory` command family
    - Expose deterministic CRUD and search/list arguments
    - Keep help text/examples aligned with the shared memory contract

Non-scope:
    - Command execution or database access
"""

from __future__ import annotations

from typing import Any

from ...schemas.memory import MemoryCategory, MemorySource
from .base import add_format_option


def add_memory_parser(subparsers: Any) -> None:
    """Add the top-level `memory` command parser."""
    from argparse import RawDescriptionHelpFormatter

    memory_parser = subparsers.add_parser(
        "memory",
        help="Manage assistant memory entries",
        description="Create, inspect, search, update, and delete durable memory entries",
    )
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)

    list_parser = memory_subparsers.add_parser(
        "list",
        help="List memory entries",
        description="List stored memory entries with deterministic filters and cursor pagination",
        epilog="""
Examples:
  cloop memory list
  cloop memory list --category preference --min-priority 25
  cloop memory list --source user_stated --limit 20
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    list_parser.add_argument("--category", choices=[category.value for category in MemoryCategory])
    list_parser.add_argument("--source", choices=[source.value for source in MemorySource])
    list_parser.add_argument("--min-priority", type=int, dest="min_priority")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--cursor")
    add_format_option(list_parser)

    search_parser = memory_subparsers.add_parser(
        "search",
        help="Search memory entries",
        description=(
            "Search stored memory entries by key/content text with deterministic pagination"
        ),
        epilog="""
Examples:
  cloop memory search "dark mode"
  cloop memory search onboarding --category context --limit 10
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    search_parser.add_argument("query", help="Search text")
    search_parser.add_argument(
        "--category",
        choices=[category.value for category in MemoryCategory],
    )
    search_parser.add_argument("--source", choices=[source.value for source in MemorySource])
    search_parser.add_argument("--min-priority", type=int, dest="min_priority")
    search_parser.add_argument("--limit", type=int, default=50)
    search_parser.add_argument("--cursor")
    add_format_option(search_parser)

    get_parser = memory_subparsers.add_parser(
        "get",
        help="Get one memory entry",
        description="Fetch a single memory entry by ID",
        epilog="""
Examples:
  cloop memory get 12
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    get_parser.add_argument("id", type=int, help="Memory entry ID")
    add_format_option(get_parser)

    create_parser = memory_subparsers.add_parser(
        "create",
        help="Create a memory entry",
        description="Create a durable memory entry with optional classification metadata",
        epilog="""
Examples:
  cloop memory create "User prefers dark mode" --category preference --priority 50
  cloop memory create "Finance owns vendor renewal" --category commitment --key owner
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    create_parser.add_argument("content", help="Memory content")
    create_parser.add_argument("--key", help="Optional identifier")
    create_parser.add_argument(
        "--category",
        choices=[category.value for category in MemoryCategory],
        default=MemoryCategory.FACT.value,
    )
    create_parser.add_argument("--priority", type=int, default=0)
    create_parser.add_argument(
        "--source",
        choices=[source.value for source in MemorySource],
        default=MemorySource.USER_STATED.value,
    )
    create_parser.add_argument(
        "--metadata-json",
        help="Optional metadata object as JSON",
    )
    add_format_option(create_parser)

    update_parser = memory_subparsers.add_parser(
        "update",
        help="Update a memory entry",
        description="Update one memory entry while preserving explicit field presence semantics",
        epilog="""
Examples:
  cloop memory update 12 --content "Updated memory"
  cloop memory update 12 --clear-key --metadata-json '{"source_app":"web"}'
  cloop memory update 12 --priority 90 --category commitment
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    update_parser.add_argument("id", type=int, help="Memory entry ID")
    update_parser.add_argument("--key", help="Set key to this value")
    update_parser.add_argument("--clear-key", action="store_true", help="Clear the key")
    update_parser.add_argument("--content", help="Replace content")
    update_parser.add_argument(
        "--category",
        choices=[category.value for category in MemoryCategory],
    )
    update_parser.add_argument("--priority", type=int)
    update_parser.add_argument("--source", choices=[source.value for source in MemorySource])
    update_parser.add_argument(
        "--metadata-json",
        help="Replace metadata with this JSON object",
    )
    add_format_option(update_parser)

    delete_parser = memory_subparsers.add_parser(
        "delete",
        help="Delete a memory entry",
        description="Delete one memory entry by ID",
        epilog="""
Examples:
  cloop memory delete 12
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    delete_parser.add_argument("id", type=int, help="Memory entry ID")
    add_format_option(delete_parser)
