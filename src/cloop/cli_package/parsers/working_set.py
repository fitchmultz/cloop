"""Working-set command argument parsers.

Purpose:
    Define the `cloop working-set` CLI surface for durable working-set CRUD,
    context management, membership edits, and exact-handle undo.

Responsibilities:
    - Add working-set parser trees for read, mutation, and undo flows
    - Document launch-ready working-set examples in CLI help text
    - Keep parser options aligned with the shared working-set service contract

Scope:
    - Argparse parser creation for top-level working-set commands only

Usage:
    - Imported by `cloop.cli_package.parser_factory` when building the full CLI

Invariants/Assumptions:
    - Exact event handles come from prior working-set responses
    - JSON flags carry transport-shaped payloads for metadata and bulk items
    - Parser help text should match the shared working-set behavior

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
        help="Manage durable working sets and focus-mode context",
        description="List, mutate, and undo durable working-set state",
    )
    sub = parser.add_subparsers(dest="working_set_command", required=True)

    list_parser = sub.add_parser(
        "list",
        help="List working sets",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set list
  cloop working-set list --format table
        """,
    )
    add_format_option(list_parser)

    get_parser = sub.add_parser(
        "get",
        help="Get one working set",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set get 12
        """,
    )
    get_parser.add_argument("id", type=int, help="Working-set ID")
    add_format_option(get_parser)

    create_parser = sub.add_parser(
        "create",
        help="Create a working set",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set create --name "Launch queue"
  cloop working-set create --name "Launch queue" --description "Bounded ship work"
        """,
    )
    create_parser.add_argument("--name", required=True, help="Working-set name")
    create_parser.add_argument("--description", help="Optional working-set description")
    add_format_option(create_parser)

    update_parser = sub.add_parser(
        "update",
        help="Update working-set metadata",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set update 12 --name "Ship queue"
  cloop working-set update 12 --clear-description
        """,
    )
    update_parser.add_argument("id", type=int, help="Working-set ID")
    update_parser.add_argument("--name", help="Replace the working-set name")
    update_parser.add_argument("--description", help="Replace the working-set description")
    update_parser.add_argument(
        "--clear-description",
        action="store_true",
        help="Clear the stored description",
    )
    add_format_option(update_parser)

    delete_parser = sub.add_parser(
        "delete",
        help="Delete one working set",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set delete 12
        """,
    )
    delete_parser.add_argument("id", type=int, help="Working-set ID")
    add_format_option(delete_parser)

    context_parser = sub.add_parser(
        "context",
        help="Inspect or update the active working-set context",
    )
    context_sub = context_parser.add_subparsers(dest="working_set_context_command", required=True)

    context_get = context_sub.add_parser("get", help="Show the active working-set context")
    add_format_option(context_get)

    context_update = context_sub.add_parser(
        "update",
        help="Update the active working-set context",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set context update --focus-mode on --active-working-set-id 12
  cloop working-set context update --focus-mode off --clear-active-working-set
        """,
    )
    context_update.add_argument(
        "--focus-mode",
        choices=["on", "off"],
        required=True,
        help="Enable or disable focus mode after the update",
    )
    context_update.add_argument("--active-working-set-id", type=int)
    context_update.add_argument(
        "--clear-active-working-set",
        action="store_true",
        help="Clear the active working set while preserving the focus-mode flag",
    )
    add_format_option(context_update)

    add_item = sub.add_parser(
        "add-item",
        help="Add one item to a working set",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set add-item --working-set 12 --item-type loop --item-id 44
  cloop working-set add-item --working-set 12 --item-type state_anchor \
    --label "Resume queue" --metadata-json '{"state":"working_set","working_set_id":12}'
        """,
    )
    add_item.add_argument("--working-set", type=int, required=True, help="Working-set ID")
    add_item.add_argument("--item-type", required=True)
    add_item.add_argument("--item-id", type=int)
    add_item.add_argument("--label")
    add_item.add_argument("--description")
    add_item.add_argument(
        "--metadata-json",
        help="Optional metadata object as JSON",
    )
    add_format_option(add_item)

    add_items_bulk = sub.add_parser(
        "add-items-bulk",
        help="Add multiple items to a working set atomically",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set add-items-bulk --working-set 12 \
    --items-json '[{"item_type":"loop","item_id":44},{"item_type":"loop","item_id":45}]'
        """,
    )
    add_items_bulk.add_argument(
        "--working-set",
        type=int,
        required=True,
        help="Working-set ID",
    )
    add_items_bulk.add_argument(
        "--items-json",
        required=True,
        help="JSON array of WorkingSetItemCreateRequest-shaped objects",
    )
    add_format_option(add_items_bulk)

    remove_item = sub.add_parser(
        "remove-item",
        help="Remove one working-set membership row",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set remove-item --working-set 12 --item-id 77
        """,
    )
    remove_item.add_argument("--working-set", type=int, required=True, help="Working-set ID")
    remove_item.add_argument("--item-id", type=int, required=True, help="Membership-row ID")
    add_format_option(remove_item)

    reorder = sub.add_parser(
        "reorder",
        help="Rewrite working-set item order",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop working-set reorder --working-set 12 --item-id 5 --item-id 7 --item-id 6
        """,
    )
    reorder.add_argument("--working-set", type=int, required=True, help="Working-set ID")
    reorder.add_argument(
        "--item-id",
        type=int,
        action="append",
        dest="ordered_item_ids",
        required=True,
        help="Repeat once per membership-row ID in the desired order",
    )
    add_format_option(reorder)

    undo = sub.add_parser(
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
