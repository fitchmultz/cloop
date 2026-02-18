"""Loop claim argument parsers.

Purpose:
    Argument parsers for loop claim commands.
"""

from __future__ import annotations

from typing import Any

from .base import add_format_option


def add_claim_parsers(loop_subparsers: Any) -> None:
    """Add all claim subcommand parsers."""
    from argparse import RawDescriptionHelpFormatter

    # loop claim
    claim_parser = loop_subparsers.add_parser(
        "claim",
        help="Claim a loop for exclusive access",
        description="Claim a loop to prevent concurrent modifications by other agents",
        epilog="""
Examples:
  # Claim a loop with default settings
  cloop loop claim 123

  # Claim with custom owner and TTL
  cloop loop claim 123 --owner agent-alpha --ttl 600
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    claim_parser.add_argument("id", type=int, help="Loop ID")
    claim_parser.add_argument(
        "--owner", "-o", default="cli-user", help="Owner identifier (default: cli-user)"
    )
    claim_parser.add_argument(
        "--ttl", "-t", type=int, default=300, help="Lease duration in seconds (default: 300)"
    )
    add_format_option(claim_parser)

    # loop renew
    renew_claim_parser = loop_subparsers.add_parser(
        "renew",
        help="Renew an existing claim",
        description="Renew a claim to extend the lease duration",
        epilog="""
Examples:
  # Renew a claim with the token
  cloop loop renew 123 --token abc123

  # Renew with custom TTL
  cloop loop renew 123 --token abc123 --ttl 600
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    renew_claim_parser.add_argument("id", type=int, help="Loop ID")
    renew_claim_parser.add_argument(
        "--token", "-t", required=True, help="Claim token from original claim"
    )
    renew_claim_parser.add_argument(
        "--ttl", type=int, default=300, help="New lease duration in seconds (default: 300)"
    )
    add_format_option(renew_claim_parser)

    # loop release
    release_claim_parser = loop_subparsers.add_parser(
        "release",
        help="Release a claim",
        description="Release a claim to allow other agents to modify the loop",
        epilog="""
Examples:
  # Release a claim
  cloop loop release 123 --token abc123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    release_claim_parser.add_argument("id", type=int, help="Loop ID")
    release_claim_parser.add_argument(
        "--token", "-t", required=True, help="Claim token from original claim"
    )
    add_format_option(release_claim_parser)

    # loop get-claim
    get_claim_parser = loop_subparsers.add_parser(
        "get-claim",
        help="Get claim status for a loop",
        description="Check the current claim status for a loop",
        epilog="""
Examples:
  # Get claim status
  cloop loop get-claim 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    get_claim_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(get_claim_parser)

    # loop claims
    list_claims_parser = loop_subparsers.add_parser(
        "claims",
        help="List active claims",
        description="List all active loop claims",
        epilog="""
Examples:
  # List all active claims
  cloop loop claims

  # Filter by owner
  cloop loop claims --owner agent-alpha
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    list_claims_parser.add_argument("--owner", "-o", help="Filter by owner")
    list_claims_parser.add_argument("--limit", type=int, default=100, help="Max results")
    add_format_option(list_claims_parser)

    # loop force-release
    force_release_parser = loop_subparsers.add_parser(
        "force-release",
        help="Force-release any claim (admin override)",
        description="Forcefully release a claim (admin only)",
        epilog="""
Examples:
  # Force release a claim
  cloop loop force-release 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    force_release_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(force_release_parser)
