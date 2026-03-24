"""Continuity diagnostics command parsers.

Purpose:
    Define the CLI surface for durable continuity diagnostics workflows.

Responsibilities:
    - Add the top-level `continuity` command family.
    - Expose delivery-diagnostics inspection arguments.
    - Keep CLI help text aligned with the shared continuity diagnostics contract.

Non-scope:
    - Command execution.
    - Delivery diagnostics business logic or storage reads.

Scope:
    - Argparse parser creation for continuity diagnostics only.

Usage:
    - Imported by `cloop.cli_package.parser_factory` when building the public CLI.

Invariants/Assumptions:
    - Delivery diagnostics pagination uses an opaque `cursor` token.
    - `limit` describes the requested number of sendable decisions, even when
      push scans inspect additional non-sendable records within the bounded scan.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from .base import add_format_option


def add_continuity_parser(subparsers: Any) -> None:
    """Add the top-level `continuity` parser."""
    parser = subparsers.add_parser(
        "continuity",
        help="Inspect durable continuity diagnostics",
        description=(
            "Inspect canonical continuity delivery decisions with the same bounded "
            "read contract used by push selection."
        ),
    )
    continuity_subparsers = parser.add_subparsers(dest="continuity_command", required=True)

    delivery_decisions = continuity_subparsers.add_parser(
        "delivery-decisions",
        help="Inspect canonical continuity delivery decisions",
        formatter_class=RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cloop continuity delivery-decisions
  cloop continuity delivery-decisions --channel push --limit 5
  cloop continuity delivery-decisions --channel push --cursor eyJ2IjoxfQ
  cloop continuity delivery-decisions --format table

Exit codes:
  0  success
  1  validation/input error
  2  resource not found
        """,
    )
    delivery_decisions.add_argument(
        "--channel",
        choices=["all", "push"],
        default="all",
        help="Inspect all continuity decisions or only push-send decisions",
    )
    delivery_decisions.add_argument(
        "--limit",
        type=int,
        default=3,
        help=(
            "Requested number of sendable decisions to target. Push scans may include "
            "additional non-sendable rows while walking the bounded scan window."
        ),
    )
    delivery_decisions.add_argument(
        "--cursor",
        help="Opaque continuation cursor returned by a prior delivery-decisions response",
    )
    add_format_option(delivery_decisions)
