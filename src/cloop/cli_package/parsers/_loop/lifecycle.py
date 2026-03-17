"""Loop lifecycle parser builders.

Purpose:
    Define the CLI parser builders for lifecycle-oriented loop commands.

Responsibilities:
    - Register `loop update`, `status`, `close`, `enrich`, and `snooze`
    - Keep lifecycle help text and options grouped together
    - Preserve stable destination names used by CLI dispatch

Scope:
    - Loop lifecycle parser construction only

Non-scope:
    - Loop command execution
    - Loop-domain validation rules beyond argparse

Usage:
    - Imported by `cloop.cli_package.parsers._loop`

Invariants/Assumptions:
    - Claim-token flags keep their established destination names
    - Format options are added uniformly via the shared helper
    - Argument names stay aligned with loop command handlers
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from typing import Any

from ..base import add_format_option


def add_loop_lifecycle_parsers(loop_subparsers: Any) -> None:
    """Register all lifecycle-oriented loop parsers."""
    _add_update_parser(loop_subparsers)
    _add_status_parser(loop_subparsers)
    _add_close_parser(loop_subparsers)
    _add_enrich_parser(loop_subparsers)
    _add_snooze_parser(loop_subparsers)


def _add_update_parser(loop_subparsers: Any) -> None:
    """Add `loop update`."""
    update_parser = loop_subparsers.add_parser(
        "update",
        help="Update loop fields",
        description="Update one or more fields on a loop",
        epilog="""
Examples:
  # Set next action
  cloop loop update 1 --next-action "Call client"

  # Set due date
  cloop loop update 1 --due-at "2026-02-20T17:00:00Z"

  # Set tags (replaces existing)
  cloop loop update 1 --tags "work,urgent"

  # Multiple fields at once
  cloop loop update 1 --title "Updated title" --urgency 0.8 --importance 0.9
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    update_parser.add_argument("id", type=int, help="Loop ID")
    update_parser.add_argument("--title", help="Update title")
    update_parser.add_argument("--summary", help="Update summary")
    update_parser.add_argument("--next-action", dest="next_action", help="Update next action")
    update_parser.add_argument("--due-at", dest="due_at", help="Update due date (ISO8601)")
    update_parser.add_argument(
        "--snooze-until",
        dest="snooze_until",
        help="Update snooze time (ISO8601)",
    )
    update_parser.add_argument(
        "--time-minutes",
        dest="time_minutes",
        type=int,
        help="Estimated time",
    )
    update_parser.add_argument(
        "--activation-energy",
        dest="activation_energy",
        type=int,
        choices=[0, 1, 2, 3],
        help="Activation energy (0-3)",
    )
    update_parser.add_argument("--urgency", type=float, help="Urgency (0.0-1.0)")
    update_parser.add_argument("--importance", type=float, help="Importance (0.0-1.0)")
    update_parser.add_argument("--project", help="Project name")
    update_parser.add_argument(
        "--blocked-reason",
        dest="blocked_reason",
        help="Reason for blocked status",
    )
    update_parser.add_argument(
        "--tags",
        help="Comma-separated tags (clears existing tags, use empty string to clear all)",
    )
    update_parser.add_argument(
        "--claim-token",
        dest="claim_token",
        help="Claim token for claimed loops",
    )
    add_format_option(update_parser)


def _add_status_parser(loop_subparsers: Any) -> None:
    """Add `loop status`."""
    status_parser = loop_subparsers.add_parser(
        "status",
        help="Transition loop status",
        description="Transition a loop to a new status",
        epilog="""
Examples:
  # Move to actionable
  cloop loop status 1 actionable

  # Move to scheduled
  cloop loop status 1 scheduled

  # Move to blocked
  cloop loop status 1 blocked

  # With claim token for claimed loop
  cloop loop status 1 actionable --claim-token TOKEN
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    status_parser.add_argument("id", type=int, help="Loop ID")
    status_parser.add_argument(
        "status",
        help="Target status (inbox, actionable, blocked, scheduled, completed, dropped)",
    )
    status_parser.add_argument(
        "--note",
        help="Optional note (used for completion_note when completing)",
    )
    status_parser.add_argument(
        "--claim-token",
        dest="claim_token",
        help="Claim token for claimed loops",
    )
    add_format_option(status_parser)


def _add_close_parser(loop_subparsers: Any) -> None:
    """Add `loop close`."""
    close_parser = loop_subparsers.add_parser(
        "close",
        help="Close a loop",
        description="Close a loop as completed or dropped",
        epilog="""
Examples:
  # Close as completed
  cloop loop close 1

  # Close as dropped
  cloop loop close 1 --dropped

  # With completion note
  cloop loop close 1 --note "Finished ahead of schedule"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    close_parser.add_argument("id", type=int, help="Loop ID")
    close_parser.add_argument(
        "--dropped",
        action="store_true",
        help="Close as dropped instead of completed",
    )
    close_parser.add_argument("--note", help="Completion/drop note")
    close_parser.add_argument(
        "--claim-token",
        dest="claim_token",
        help="Claim token for claimed loops",
    )
    add_format_option(close_parser)


def _add_enrich_parser(loop_subparsers: Any) -> None:
    """Add `loop enrich`."""
    enrich_parser = loop_subparsers.add_parser(
        "enrich",
        help="Run AI enrichment for a loop",
    )
    enrich_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(enrich_parser)


def _add_snooze_parser(loop_subparsers: Any) -> None:
    """Add `loop snooze`."""
    snooze_parser = loop_subparsers.add_parser(
        "snooze",
        help="Snooze a loop",
        description="Temporarily hide a loop until a future time",
        epilog="""
Examples:
  # Snooze for 30 minutes
  cloop loop snooze 1 30m

  # Snooze for 2 hours
  cloop loop snooze 1 2h

  # Snooze for 3 days
  cloop loop snooze 1 3d

  # Snooze until specific time
  cloop loop snooze 1 "2026-02-20T09:00:00Z"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    snooze_parser.add_argument("id", type=int, help="Loop ID")
    snooze_parser.add_argument(
        "duration",
        help="Duration (30m, 1h, 2d, 1w) or ISO8601 timestamp",
    )
    add_format_option(snooze_parser)
