"""Planning workflow command argument parsers.

Purpose:
    Define the `cloop plan` CLI surface for saved AI-native planning sessions.

Responsibilities:
    - Add planning-session parser trees
    - Expose parser options that map cleanly onto shared planning-workflow inputs
    - Document common planning workflows in help text

Non-scope:
    - Planning workflow execution
    - Transport-independent validation beyond argparse-level parsing
    - Output formatting
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from .base import add_format_option


def add_plan_parser(subparsers: Any) -> None:
    """Add the top-level `plan` parser."""
    plan_parser = subparsers.add_parser(
        "plan",
        help="AI-native planning sessions with explicit checkpoints",
    )
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", required=True)
    _add_session_parser(plan_subparsers)


def _add_session_parser(plan_subparsers: Any) -> None:
    parser = plan_subparsers.add_parser(
        "session",
        help="Manage saved planning sessions",
    )
    sub = parser.add_subparsers(dest="plan_session_command", required=True)

    create = sub.add_parser(
        "create",
        help="Create a planning session",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop plan session create \
    --name weekly-reset \
    --prompt "Create a checkpointed plan for cleaning up my open loops this week" \
    --query "status:open"
  cloop plan session create \
    --name launch-prep \
    --prompt "Plan the next steps for launch readiness" \
    --query "project:launch status:open" \
    --include-rag-context --rag-scope launch
        """,
    )
    create.add_argument("--name", required=True)
    create.add_argument("--prompt", required=True)
    create.add_argument("--query")
    create.add_argument("--loop-limit", type=int, default=10)
    create.add_argument(
        "--include-memory-context",
        dest="include_memory_context",
        action="store_true",
    )
    create.add_argument(
        "--no-memory-context",
        dest="include_memory_context",
        action="store_false",
    )
    create.set_defaults(include_memory_context=True)
    create.add_argument("--include-rag-context", action="store_true")
    create.add_argument("--rag-k", type=int, default=5)
    create.add_argument("--rag-scope")
    add_format_option(create)

    list_parser = sub.add_parser("list", help="List saved planning sessions")
    add_format_option(list_parser)

    get_parser = sub.add_parser("get", help="Load a planning session snapshot")
    get_parser.add_argument("id", type=int)
    add_format_option(get_parser)

    move = sub.add_parser("move", help="Move a planning session checkpoint cursor")
    move.add_argument("--session", type=int, required=True)
    move.add_argument("--direction", choices=["next", "previous"], required=True)
    add_format_option(move)

    refresh = sub.add_parser(
        "refresh",
        help="Regenerate a planning session against current grounded context",
    )
    refresh.add_argument("--session", type=int, required=True)
    add_format_option(refresh)

    execute = sub.add_parser(
        "execute",
        help="Execute the current checkpoint in a planning session",
    )
    execute.add_argument("--session", type=int, required=True)
    add_format_option(execute)

    delete = sub.add_parser("delete", help="Delete a planning session")
    delete.add_argument("id", type=int)
    add_format_option(delete)
