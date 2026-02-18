"""Loop timer argument parsers.

Purpose:
    Argument parsers for loop timer commands.
"""

from __future__ import annotations

from typing import Any


def add_timer_parser(loop_subparsers: Any) -> None:
    """Add timer subcommand parsers."""
    from argparse import RawDescriptionHelpFormatter

    timer_parser = loop_subparsers.add_parser(
        "timer",
        help="Start/stop timer for a loop",
        description="Track time spent working on a loop",
        epilog="""
Examples:
  # Start timer
  cloop loop timer start 1

  # Check timer status
  cloop loop timer status 1

  # Stop timer with notes
  cloop loop timer stop 1 --notes "Completed analysis"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    timer_subparsers = timer_parser.add_subparsers(dest="timer_action", required=True)

    timer_start_parser = timer_subparsers.add_parser(
        "start",
        help="Start timer",
        description="Start a timer for time tracking on a loop",
        epilog="""
Examples:
  # Start timer for loop
  cloop loop timer start 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    timer_start_parser.add_argument("id", type=int, help="Loop ID")

    timer_stop_parser = timer_subparsers.add_parser(
        "stop",
        help="Stop timer",
        description="Stop the active timer for a loop",
        epilog="""
Examples:
  # Stop timer
  cloop loop timer stop 123

  # Stop timer with notes
  cloop loop timer stop 123 --notes "Completed analysis"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    timer_stop_parser.add_argument("id", type=int, help="Loop ID")
    timer_stop_parser.add_argument("--notes", help="Optional notes for this session")

    timer_status_parser = timer_subparsers.add_parser(
        "status",
        help="Get timer status",
        description="Check the current timer status for a loop",
        epilog="""
Examples:
  # Check timer status
  cloop loop timer status 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    timer_status_parser.add_argument("id", type=int, help="Loop ID")


def add_sessions_parser(loop_subparsers: Any) -> None:
    """Add sessions subcommand parser."""
    from argparse import RawDescriptionHelpFormatter

    sessions_parser = loop_subparsers.add_parser(
        "sessions",
        help="List time sessions for a loop",
        description="List all time tracking sessions for a loop",
        epilog="""
Examples:
  # List sessions for loop
  cloop loop sessions 123

  # List with custom limit
  cloop loop sessions 123 --limit 50
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    sessions_parser.add_argument("id", type=int, help="Loop ID")
    sessions_parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
