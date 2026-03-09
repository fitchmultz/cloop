"""Loop claim argument parsers.

Purpose:
    Argument parsers for loop claim commands.

Responsibilities:
    - Define argument parsers for claim, renew, release, get-claim, claims,
      and force-release subcommands
    - Configure CLI options for owner, TTL, tokens, and filtering
    - Provide epilog examples for each command

Non-scope:
    - Does NOT implement claim logic or business rules
    - Does NOT handle claim validation or token generation
    - Does NOT perform database operations
"""

from __future__ import annotations

from typing import Any

from .base import add_command_parser, add_format_option


def add_claim_parsers(loop_subparsers: Any) -> None:
    """Add all claim subcommand parsers."""
    claim_parser = add_command_parser(
        loop_subparsers,
        "claim",
        help_text="Claim a loop for exclusive access",
        description="Claim a loop to prevent concurrent modifications by other agents",
        examples="""
Examples:
  # Claim a loop with default settings
  cloop loop claim 123

  # Claim with custom owner and TTL
  cloop loop claim 123 --owner agent-alpha --ttl 600
        """,
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
    renew_claim_parser = add_command_parser(
        loop_subparsers,
        "renew",
        help_text="Renew an existing claim",
        description="Renew a claim to extend the lease duration",
        examples="""
Examples:
  # Renew a claim with the token
  cloop loop renew 123 --token abc123

  # Renew with custom TTL
  cloop loop renew 123 --token abc123 --ttl 600
        """,
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
    release_claim_parser = add_command_parser(
        loop_subparsers,
        "release",
        help_text="Release a claim",
        description="Release a claim to allow other agents to modify the loop",
        examples="""
Examples:
  # Release a claim
  cloop loop release 123 --token abc123
        """,
    )
    release_claim_parser.add_argument("id", type=int, help="Loop ID")
    release_claim_parser.add_argument(
        "--token", "-t", required=True, help="Claim token from original claim"
    )
    add_format_option(release_claim_parser)

    # loop get-claim
    get_claim_parser = add_command_parser(
        loop_subparsers,
        "get-claim",
        help_text="Get claim status for a loop",
        description="Check the current claim status for a loop",
        examples="""
Examples:
  # Get claim status
  cloop loop get-claim 123
        """,
    )
    get_claim_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(get_claim_parser)

    # loop claims
    list_claims_parser = add_command_parser(
        loop_subparsers,
        "claims",
        help_text="List active claims",
        description="List all active loop claims",
        examples="""
Examples:
  # List all active claims
  cloop loop claims

  # Filter by owner
  cloop loop claims --owner agent-alpha
        """,
    )
    list_claims_parser.add_argument("--owner", "-o", help="Filter by owner")
    list_claims_parser.add_argument("--limit", type=int, default=100, help="Max results")
    add_format_option(list_claims_parser)

    # loop force-release
    force_release_parser = add_command_parser(
        loop_subparsers,
        "force-release",
        help_text="Force-release any claim (admin override)",
        description="Forcefully release a claim (admin only)",
        examples="""
Examples:
  # Force release a claim
  cloop loop force-release 123
        """,
    )
    force_release_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(force_release_parser)
