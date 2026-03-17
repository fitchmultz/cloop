"""Internal loop-parser package.

Purpose:
    Hold the focused parser builders behind the public `parsers.loop` facade.

Responsibilities:
    - Wire loop subcommand parser groups together in one place
    - Delegate parser construction to focused feature-owned modules
    - Keep the public `add_loop_parser()` surface stable and small

Scope:
    - Loop CLI parser construction only

Usage:
    - Imported by `cloop.cli_package.parsers.loop`

Invariants/Assumptions:
    - The registration order defines the public CLI help ordering
    - Claim/timer/misc parsers continue to be delegated to their existing modules
    - Dispatch relies on stable destination names such as `loop_command`
"""

from __future__ import annotations

from typing import Any

from .bulk import add_bulk_parser
from .dependencies import add_dependency_parsers
from .lifecycle import add_loop_lifecycle_parsers
from .reads import add_loop_read_parsers
from .relationships import add_relationship_parsers
from .views import add_view_parsers


def add_loop_parser(subparsers: Any) -> None:
    """Add the public `loop` command and all nested subcommands."""
    from ..loop_claim_parsers import add_claim_parsers
    from ..loop_misc_parsers import add_misc_loop_parsers
    from ..loop_timer_parsers import add_sessions_parser, add_timer_parser

    loop_parser = subparsers.add_parser("loop", help="Loop lifecycle commands")
    loop_subparsers = loop_parser.add_subparsers(dest="loop_command", required=True)

    add_loop_read_parsers(loop_subparsers)
    add_loop_lifecycle_parsers(loop_subparsers)
    add_relationship_parsers(loop_subparsers)
    add_view_parsers(loop_subparsers)
    add_dependency_parsers(loop_subparsers)
    add_bulk_parser(loop_subparsers)

    add_claim_parsers(loop_subparsers)
    add_timer_parser(loop_subparsers)
    add_sessions_parser(loop_subparsers)
    add_misc_loop_parsers(loop_subparsers)
