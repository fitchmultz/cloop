"""Loop relationship-review parser builders.

Purpose:
    Define the CLI parser builders for loop relationship review workflows.

Responsibilities:
    - Register `loop relationship` subcommands
    - Keep duplicate/related review help text together
    - Preserve dispatch destination names for relationship commands

Scope:
    - Relationship-review parser construction only

Non-scope:
    - Relationship review execution
    - Similarity or relationship persistence logic

Usage:
    - Imported by `cloop.cli_package.parsers._loop`

Invariants/Assumptions:
    - Relationship subcommands use the `relationship_command` destination
    - Status scopes share the canonical loop-status help text
    - Output-format flags are added consistently through the shared helper
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from ..base import LOOP_STATUS_VALUES, add_format_option


def add_relationship_parsers(loop_subparsers: Any) -> None:
    """Add relationship-review subcommand parsers."""
    relationship_parser = loop_subparsers.add_parser(
        "relationship",
        help="Review and decide duplicate/related loop relationships",
    )
    relationship_subparsers = relationship_parser.add_subparsers(
        dest="relationship_command",
        required=True,
    )

    review_parser = relationship_subparsers.add_parser(
        "review",
        help="Review duplicate/related candidates for one loop",
        description=(
            "Review duplicate and related-loop candidates for one loop "
            "using shared semantic similarity"
        ),
        epilog="""
Examples:
  # Review both duplicate and related candidates for loop 42
  cloop loop relationship review --loop 42

  # Only consider inbox candidates
  cloop loop relationship review --loop 42 --status inbox
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    review_parser.add_argument("--loop", type=int, required=True, help="Loop ID to review")
    review_parser.add_argument(
        "--status",
        default="open",
        help=f"Candidate status scope ({LOOP_STATUS_VALUES})",
    )
    review_parser.add_argument(
        "--duplicate-limit",
        type=int,
        default=10,
        help="Max duplicate candidates to return (default: 10)",
    )
    review_parser.add_argument(
        "--related-limit",
        type=int,
        default=10,
        help="Max related candidates to return (default: 10)",
    )
    add_format_option(review_parser)

    queue_parser = relationship_subparsers.add_parser(
        "queue",
        help="List loops with pending duplicate/related review work",
        description=(
            "List loops that currently have pending duplicate or related-loop review candidates"
        ),
        epilog="""
Examples:
  # Review all pending relationship work
  cloop loop relationship queue

  # Only duplicate-review work
  cloop loop relationship queue --kind duplicate --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    queue_parser.add_argument(
        "--status",
        default="open",
        help=f"Loop status scope ({LOOP_STATUS_VALUES})",
    )
    queue_parser.add_argument(
        "--kind",
        choices=["all", "duplicate", "related"],
        default="all",
        help="Queue kind to show (default: all)",
    )
    queue_parser.add_argument("--limit", type=int, default=25, help="Max loops to return")
    queue_parser.add_argument(
        "--candidate-limit",
        type=int,
        default=3,
        help="Max candidates to preview per loop",
    )
    add_format_option(queue_parser)

    confirm_parser = relationship_subparsers.add_parser(
        "confirm",
        help="Confirm one relationship candidate",
        description="Persist a duplicate or related relationship decision for a loop pair",
        formatter_class=RawDescriptionHelpFormatter,
    )
    confirm_parser.add_argument("--loop", type=int, required=True, help="Source loop ID")
    confirm_parser.add_argument(
        "--candidate",
        type=int,
        required=True,
        help="Candidate loop ID",
    )
    confirm_parser.add_argument(
        "--type",
        choices=["related", "duplicate"],
        required=True,
        help="Relationship type to confirm",
    )
    add_format_option(confirm_parser)

    dismiss_parser = relationship_subparsers.add_parser(
        "dismiss",
        help="Dismiss one relationship candidate",
        description="Dismiss a duplicate or related relationship suggestion for a loop pair",
        formatter_class=RawDescriptionHelpFormatter,
    )
    dismiss_parser.add_argument("--loop", type=int, required=True, help="Source loop ID")
    dismiss_parser.add_argument(
        "--candidate",
        type=int,
        required=True,
        help="Candidate loop ID",
    )
    dismiss_parser.add_argument(
        "--type",
        choices=["related", "duplicate"],
        required=True,
        help="Relationship type to dismiss",
    )
    add_format_option(dismiss_parser)
