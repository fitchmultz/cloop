"""Review workflow command argument parsers.

Purpose:
    Define the `cloop review` CLI surface for saved review actions and
    session-preserving relationship/enrichment review workflows.

Responsibilities:
    - Add review action/session parser trees for relationship and enrichment work
    - Expose parser options that map cleanly onto shared review-workflow inputs
    - Document common saved-session and saved-action usage examples in help text

Non-scope:
    - Review workflow execution
    - Transport-independent validation beyond argparse-level parsing
    - Output formatting
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from .base import add_format_option


def add_review_parser(subparsers: Any) -> None:
    """Add the top-level `review` parser."""
    review_parser = subparsers.add_parser(
        "review",
        help="Saved review actions and session-preserving review workflows",
    )
    review_subparsers = review_parser.add_subparsers(dest="review_command", required=True)

    _add_relationship_action_parser(review_subparsers)
    _add_relationship_session_parser(review_subparsers)
    _add_enrichment_action_parser(review_subparsers)
    _add_enrichment_session_parser(review_subparsers)


def _add_relationship_action_parser(review_subparsers: Any) -> None:
    parser = review_subparsers.add_parser(
        "relationship-action",
        help="Manage saved relationship-review actions",
    )
    sub = parser.add_subparsers(dest="review_relationship_action_command", required=True)

    create = sub.add_parser(
        "create",
        help="Create a saved relationship-review action",
        formatter_class=RawDescriptionHelpFormatter,
    )
    create.add_argument("--name", required=True)
    create.add_argument("--action", choices=["confirm", "dismiss"], required=True)
    create.add_argument(
        "--relationship-type",
        choices=["suggested", "duplicate", "related"],
        default="suggested",
    )
    create.add_argument("--description")
    add_format_option(create)

    list_parser = sub.add_parser("list", help="List saved relationship-review actions")
    add_format_option(list_parser)

    get_parser = sub.add_parser("get", help="Show one relationship-review action")
    get_parser.add_argument("id", type=int)
    add_format_option(get_parser)

    update = sub.add_parser("update", help="Update a saved relationship-review action")
    update.add_argument("id", type=int)
    update.add_argument("--name")
    update.add_argument("--action", choices=["confirm", "dismiss"])
    update.add_argument("--relationship-type", choices=["suggested", "duplicate", "related"])
    update.add_argument("--description")
    add_format_option(update)

    delete = sub.add_parser("delete", help="Delete a saved relationship-review action")
    delete.add_argument("id", type=int)
    add_format_option(delete)


def _add_relationship_session_parser(review_subparsers: Any) -> None:
    parser = review_subparsers.add_parser(
        "relationship-session",
        help="Manage saved relationship-review sessions",
    )
    sub = parser.add_subparsers(dest="review_relationship_session_command", required=True)

    create = sub.add_parser(
        "create",
        help="Create a relationship-review session",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop review relationship-session create --name inbox-dupes --query "status:open" --kind duplicate
  cloop review relationship-session create --name project-alpha --query "project:alpha status:open"
        """,
    )
    create.add_argument("--name", required=True)
    create.add_argument("--query", required=True)
    create.add_argument("--kind", choices=["all", "duplicate", "related"], default="all")
    create.add_argument("--candidate-limit", type=int, default=3)
    create.add_argument("--item-limit", type=int, default=25)
    create.add_argument("--current-loop-id", type=int)
    add_format_option(create)

    list_parser = sub.add_parser("list", help="List saved relationship-review sessions")
    add_format_option(list_parser)

    get_parser = sub.add_parser("get", help="Load a relationship-review session snapshot")
    get_parser.add_argument("id", type=int)
    add_format_option(get_parser)

    update = sub.add_parser("update", help="Update a relationship-review session")
    update.add_argument("id", type=int)
    update.add_argument("--name")
    update.add_argument("--query")
    update.add_argument("--kind", choices=["all", "duplicate", "related"])
    update.add_argument("--candidate-limit", type=int)
    update.add_argument("--item-limit", type=int)
    update.add_argument("--current-loop-id", type=int)
    update.add_argument("--clear-current-loop", action="store_true")
    add_format_option(update)

    delete = sub.add_parser("delete", help="Delete a relationship-review session")
    delete.add_argument("id", type=int)
    add_format_option(delete)

    apply_action = sub.add_parser(
        "apply-action",
        help="Run a relationship-review action inside a saved session",
    )
    apply_action.add_argument("--session", type=int, required=True)
    apply_action.add_argument("--loop", type=int, required=True)
    apply_action.add_argument("--candidate", type=int, required=True)
    apply_action.add_argument(
        "--candidate-type",
        choices=["duplicate", "related"],
        required=True,
    )
    apply_action.add_argument("--action-id", type=int)
    apply_action.add_argument("--action", choices=["confirm", "dismiss"])
    apply_action.add_argument(
        "--relationship-type",
        choices=["suggested", "duplicate", "related"],
    )
    add_format_option(apply_action)


def _add_enrichment_action_parser(review_subparsers: Any) -> None:
    parser = review_subparsers.add_parser(
        "enrichment-action",
        help="Manage saved enrichment-review actions",
    )
    sub = parser.add_subparsers(dest="review_enrichment_action_command", required=True)

    create = sub.add_parser("create", help="Create a saved enrichment-review action")
    create.add_argument("--name", required=True)
    create.add_argument("--action", choices=["apply", "reject"], required=True)
    create.add_argument("--fields", help="Comma-separated suggestion fields for apply actions")
    create.add_argument("--description")
    add_format_option(create)

    list_parser = sub.add_parser("list", help="List saved enrichment-review actions")
    add_format_option(list_parser)

    get_parser = sub.add_parser("get", help="Show one enrichment-review action")
    get_parser.add_argument("id", type=int)
    add_format_option(get_parser)

    update = sub.add_parser("update", help="Update a saved enrichment-review action")
    update.add_argument("id", type=int)
    update.add_argument("--name")
    update.add_argument("--action", choices=["apply", "reject"])
    update.add_argument("--fields", help="Comma-separated suggestion fields for apply actions")
    update.add_argument("--description")
    add_format_option(update)

    delete = sub.add_parser("delete", help="Delete a saved enrichment-review action")
    delete.add_argument("id", type=int)
    add_format_option(delete)


def _add_enrichment_session_parser(review_subparsers: Any) -> None:
    parser = review_subparsers.add_parser(
        "enrichment-session",
        help="Manage saved enrichment-review sessions",
    )
    sub = parser.add_subparsers(dest="review_enrichment_session_command", required=True)

    create = sub.add_parser(
        "create",
        help="Create an enrichment-review session",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop review enrichment-session create \
    --name pending-ai --query "status:open" --pending-kind all
  cloop review enrichment-session create \
    --name clarifications --query "project:alpha" --pending-kind clarifications
        """,
    )
    create.add_argument("--name", required=True)
    create.add_argument("--query", required=True)
    create.add_argument(
        "--pending-kind",
        choices=["all", "suggestions", "clarifications"],
        default="all",
    )
    create.add_argument("--suggestion-limit", type=int, default=3)
    create.add_argument("--clarification-limit", type=int, default=3)
    create.add_argument("--item-limit", type=int, default=25)
    create.add_argument("--current-loop-id", type=int)
    add_format_option(create)

    list_parser = sub.add_parser("list", help="List saved enrichment-review sessions")
    add_format_option(list_parser)

    get_parser = sub.add_parser("get", help="Load an enrichment-review session snapshot")
    get_parser.add_argument("id", type=int)
    add_format_option(get_parser)

    update = sub.add_parser("update", help="Update an enrichment-review session")
    update.add_argument("id", type=int)
    update.add_argument("--name")
    update.add_argument("--query")
    update.add_argument("--pending-kind", choices=["all", "suggestions", "clarifications"])
    update.add_argument("--suggestion-limit", type=int)
    update.add_argument("--clarification-limit", type=int)
    update.add_argument("--item-limit", type=int)
    update.add_argument("--current-loop-id", type=int)
    update.add_argument("--clear-current-loop", action="store_true")
    add_format_option(update)

    delete = sub.add_parser("delete", help="Delete an enrichment-review session")
    delete.add_argument("id", type=int)
    add_format_option(delete)

    apply_action = sub.add_parser(
        "apply-action",
        help="Run an enrichment-review action inside a saved session",
    )
    apply_action.add_argument("--session", type=int, required=True)
    apply_action.add_argument("--suggestion", type=int, required=True)
    apply_action.add_argument("--action-id", type=int)
    apply_action.add_argument("--action", choices=["apply", "reject"])
    apply_action.add_argument(
        "--fields", help="Comma-separated suggestion fields for apply actions"
    )
    add_format_option(apply_action)

    answer = sub.add_parser(
        "answer-clarifications",
        help="Answer clarifications for one loop in an enrichment session",
    )
    answer.add_argument("--session", type=int, required=True)
    answer.add_argument("--loop", type=int, required=True)
    answer.add_argument(
        "--item",
        action="append",
        required=True,
        help="Answer item formatted as <clarification_id>=<answer>",
    )
    add_format_option(answer)
