"""Loop dependency parser builders.

Purpose:
    Define the CLI parser builders for loop dependency-management commands.

Responsibilities:
    - Register `loop dep` subcommands
    - Keep dependency help text together
    - Preserve stable destination names used by CLI dispatch

Scope:
    - Dependency parser construction only

Non-scope:
    - Dependency mutation execution
    - Dependency graph business rules

Usage:
    - Imported by `cloop.cli_package.parsers._loop`

Invariants/Assumptions:
    - Dependency subcommands use the `dep_action` destination
    - Loop identifiers keep the historical `loop_id` / `depends_on` destinations
    - Format flags are added consistently through the shared helper
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from ..base import add_format_option


def add_dependency_parsers(loop_subparsers: Any) -> None:
    """Add all dependency subcommand parsers."""
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
        "--loop",
        "-l",
        type=int,
        dest="loop_id",
        required=True,
        help="Loop ID",
    )
    dep_add_parser.add_argument(
        "--on",
        "-o",
        type=int,
        dest="depends_on",
        required=True,
        help="Depends on loop ID",
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
        "--loop",
        "-l",
        type=int,
        dest="loop_id",
        required=True,
        help="Loop ID",
    )
    dep_remove_parser.add_argument(
        "--on",
        "-o",
        type=int,
        dest="depends_on",
        required=True,
        help="Depends on loop ID",
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
        "--loop",
        "-l",
        type=int,
        dest="loop_id",
        required=True,
        help="Loop ID",
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
        "--loop",
        "-l",
        type=int,
        dest="loop_id",
        required=True,
        help="Loop ID",
    )
    add_format_option(dep_blocking_parser)
