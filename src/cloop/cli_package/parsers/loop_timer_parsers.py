"""Loop timer argument parsers.

Purpose:
    Argument parsers for loop timer commands.

Responsibilities:
    - Define argument parsers for timer start, stop, status, and sessions subcommands
    - Configure CLI options for loop ID and session notes
    - Provide epilog examples for each command

Non-scope:
    - Does NOT implement timer logic or time tracking
    - Does NOT persist or retrieve session data
    - Does NOT calculate elapsed time or aggregate statistics
"""

from __future__ import annotations

from typing import Any

from .base import add_command_parser


def add_timer_parser(loop_subparsers: Any) -> None:
    """Add timer subcommand parsers."""
    timer_parser = add_command_parser(
        loop_subparsers,
        "timer",
        help_text="Start/stop timer for a loop",
        description="Track time spent working on a loop",
        examples="""
Examples:
  # Start timer
  cloop loop timer start 1

  # Check timer status
  cloop loop timer status 1

  # Stop timer with notes
  cloop loop timer stop 1 --notes "Completed analysis"
        """,
    )
    timer_subparsers = timer_parser.add_subparsers(dest="timer_action", required=True)

    timer_start_parser = add_command_parser(
        timer_subparsers,
        "start",
        help_text="Start timer",
        description="Start a timer for time tracking on a loop",
        examples="""
Examples:
  # Start timer for loop
  cloop loop timer start 123
        """,
    )
    timer_start_parser.add_argument("id", type=int, help="Loop ID")

    timer_stop_parser = add_command_parser(
        timer_subparsers,
        "stop",
        help_text="Stop timer",
        description="Stop the active timer for a loop",
        examples="""
Examples:
  # Stop timer
  cloop loop timer stop 123

  # Stop timer with notes
  cloop loop timer stop 123 --notes "Completed analysis"
        """,
    )
    timer_stop_parser.add_argument("id", type=int, help="Loop ID")
    timer_stop_parser.add_argument("--notes", help="Optional notes for this session")

    timer_status_parser = add_command_parser(
        timer_subparsers,
        "status",
        help_text="Get timer status",
        description="Check the current timer status for a loop",
        examples="""
Examples:
  # Check timer status
  cloop loop timer status 123
        """,
    )
    timer_status_parser.add_argument("id", type=int, help="Loop ID")


def add_sessions_parser(loop_subparsers: Any) -> None:
    """Add sessions subcommand parser."""
    sessions_parser = add_command_parser(
        loop_subparsers,
        "sessions",
        help_text="List time sessions for a loop",
        description="List all time tracking sessions for a loop",
        examples="""
Examples:
  # List sessions for loop
  cloop loop sessions 123

  # List with custom limit
  cloop loop sessions 123 --limit 50
        """,
    )
    sessions_parser.add_argument("id", type=int, help="Loop ID")
    sessions_parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
