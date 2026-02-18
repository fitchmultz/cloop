"""Loop misc argument parsers.

Purpose:
    Argument parsers for miscellaneous loop commands.
"""

from __future__ import annotations

from typing import Any

from ...constants import DEFAULT_LOOP_LIST_LIMIT, DEFAULT_LOOP_NEXT_LIMIT
from .base import add_format_option


def add_capture_parser(subparsers: Any) -> None:
    """Add 'capture' command parser."""
    from argparse import RawDescriptionHelpFormatter

    capture_parser = subparsers.add_parser(
        "capture",
        help="Capture a loop",
        description="Capture a new loop with optional status flags and recurrence",
        epilog="""
Examples:
  # Quick capture to inbox (default)
  cloop capture "Buy groceries"

  # Capture as actionable task
  cloop capture "Review PR #42" --actionable

  # Capture as blocked
  cloop capture "Deploy to prod" --blocked

  # Capture with recurrence (every weekday)
  cloop capture "Daily standup" --schedule "every weekday" --actionable

  # Capture with template
  cloop capture "Weekly report" --template weekly-report

  # Capture with explicit RRULE
  cloop capture "Monthly review" --rrule "FREQ=MONTHLY;BYDAY=1FR"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    capture_parser.add_argument("text", help="Raw text to capture")
    capture_parser.add_argument(
        "--captured-at",
        dest="captured_at",
        help="ISO8601 timestamp (defaults to now)",
    )
    capture_parser.add_argument(
        "--tz-offset-min",
        dest="tz_offset_min",
        type=int,
        help="Timezone offset minutes from UTC",
    )
    capture_parser.add_argument(
        "--actionable",
        action="store_true",
        help="Mark as actionable",
    )
    capture_parser.add_argument(
        "--urgent",
        action="store_true",
        dest="actionable",
        help="Alias for --actionable",
    )
    capture_parser.add_argument("--scheduled", action="store_true", help="Mark as scheduled")
    capture_parser.add_argument(
        "--blocked",
        action="store_true",
        help="Mark as blocked",
    )
    capture_parser.add_argument(
        "--waiting",
        action="store_true",
        dest="blocked",
        help="Alias for --blocked",
    )
    capture_parser.add_argument(
        "--schedule",
        dest="schedule",
        help=(
            "Natural-language recurrence schedule (e.g., 'every weekday', "
            "'every 2 weeks', 'every 1st business day')"
        ),
    )
    capture_parser.add_argument(
        "--rrule",
        dest="rrule",
        help="RFC 5545 RRULE string (e.g., 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')",
    )
    capture_parser.add_argument(
        "--timezone",
        dest="timezone",
        help="IANA timezone name (e.g., 'America/New_York'). Defaults to client offset.",
    )
    capture_parser.add_argument(
        "--template",
        "-t",
        dest="template",
        help="Template name or ID to apply",
    )
    capture_parser.add_argument(
        "--due",
        dest="due",
        help="Due date (ISO8601 format, e.g., 2026-04-15 or 2026-04-15T17:00:00)",
    )
    capture_parser.add_argument(
        "--next-action",
        dest="next_action",
        help="Immediate next action to take",
    )
    capture_parser.add_argument(
        "--time",
        dest="time_minutes",
        type=int,
        help="Estimated time to complete (minutes)",
    )
    capture_parser.add_argument(
        "--effort",
        dest="activation_energy",
        type=int,
        choices=[0, 1, 2, 3],
        help="Effort level: 0=trivial, 1=easy, 2=medium, 3=hard",
    )
    capture_parser.add_argument(
        "--project",
        dest="project",
        help="Project name to associate",
    )
    capture_parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        help="Tag to apply (can be specified multiple times)",
    )


def add_inbox_parser(subparsers: Any) -> None:
    """Add 'inbox' command parser."""
    from argparse import RawDescriptionHelpFormatter

    inbox_parser = subparsers.add_parser(
        "inbox",
        help="List inbox loops",
        description="List loops in inbox status",
        epilog="""
Examples:
  # List inbox loops (default limit)
  cloop inbox

  # List with custom limit
  cloop inbox --limit 20
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    inbox_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LOOP_LIST_LIMIT, help="Max loops to return"
    )


def add_next_parser(subparsers: Any) -> None:
    """Add 'next' command parser."""
    from argparse import RawDescriptionHelpFormatter

    next_parser = subparsers.add_parser(
        "next",
        help="Show the next loops",
        description="Show prioritized next actions grouped by urgency/importance",
        epilog="""
Examples:
  # Show next actions (default)
  cloop next

  # Show more items per bucket
  cloop next --limit 10
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    next_parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LOOP_NEXT_LIMIT,
        help="Max total loops across all buckets",
    )


def add_tags_parser(subparsers: Any) -> None:
    """Add 'tags' command parser."""
    from argparse import RawDescriptionHelpFormatter

    tags_parser = subparsers.add_parser(
        "tags",
        help="List all tags",
        description="List all tags used across loops",
        epilog="""
Examples:
  # List all tags as JSON
  cloop tags

  # List tags in table format
  cloop tags --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    add_format_option(tags_parser)


def add_projects_parser(subparsers: Any) -> None:
    """Add 'projects' command parser."""
    from argparse import RawDescriptionHelpFormatter

    projects_parser = subparsers.add_parser(
        "projects",
        help="List all projects",
        description="List all project names used across loops",
        epilog="""
Examples:
  # List all projects as JSON
  cloop projects

  # List projects in table format
  cloop projects --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    add_format_option(projects_parser)


def add_export_parser(subparsers: Any) -> None:
    """Add 'export' command parser."""
    from argparse import RawDescriptionHelpFormatter

    export_parser = subparsers.add_parser(
        "export",
        help="Export loops",
        description="Export all loops to JSON",
        epilog="""
Examples:
  # Export to stdout
  cloop export

  # Export to file
  cloop export --output backup.json

  # Export and view as table
  cloop export --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    export_parser.add_argument("--output", help="Write to file instead of stdout")
    add_format_option(export_parser)


def add_import_parser(subparsers: Any) -> None:
    """Add 'import' command parser."""
    from argparse import RawDescriptionHelpFormatter

    import_parser = subparsers.add_parser(
        "import",
        help="Import loops",
        description="Import loops from JSON (previously exported)",
        epilog="""
Examples:
  # Import from file
  cloop import --file backup.json

  # Import from stdin (pipe)
  cat backup.json | cloop import
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    import_parser.add_argument("--file", help="Read from file instead of stdin")
    add_format_option(import_parser)


def add_misc_loop_parsers(loop_subparsers: Any) -> None:
    """Add review, events, undo, metrics parsers."""
    from argparse import RawDescriptionHelpFormatter

    # loop review
    review_parser = loop_subparsers.add_parser(
        "review",
        help="Show review cohorts for maintenance",
        description="Display daily/weekly review cohorts for stale-loop cleanup",
        epilog="""
Examples:
  # Show daily review cohorts (default)
  cloop loop review

  # Show weekly review cohorts
  cloop loop review --weekly

  # Show both daily and weekly
  cloop loop review --all

  # Filter to specific cohort
  cloop loop review --cohort stale

  # Show in table format
  cloop loop review --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    review_parser.add_argument(
        "--daily",
        action="store_true",
        help="Show daily review cohorts (default behavior)",
    )
    review_parser.add_argument(
        "--weekly",
        action="store_true",
        help="Show weekly review cohorts (stale, blocked_too_long)",
    )
    review_parser.add_argument(
        "--all",
        action="store_true",
        help="Show both daily and weekly cohorts",
    )
    review_parser.add_argument(
        "--cohort",
        choices=["stale", "no_next_action", "blocked_too_long", "due_soon_unplanned"],
        help="Filter to specific cohort",
    )
    review_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max items per cohort (default: 50)",
    )
    add_format_option(review_parser)

    # loop events
    events_parser = loop_subparsers.add_parser(
        "events",
        help="Show event history for a loop",
        description="Display the activity timeline for a loop",
        epilog="""
Examples:
  # Show recent events for a loop
  cloop loop events 123

  # Show events with pagination
  cloop loop events 123 --limit 20 --before 500

  # Show in table format
  cloop loop events 123 --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    events_parser.add_argument("id", type=int, help="Loop ID")
    events_parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    events_parser.add_argument("--before", type=int, help="Show events before this event ID")
    add_format_option(events_parser)

    # loop undo
    undo_parser = loop_subparsers.add_parser(
        "undo",
        help="Undo the last reversible action",
        description=(
            "Undo the most recent reversible event (update, status_change, close). "
            "This restores the loop to its previous state."
        ),
        epilog="""
Examples:
  # Undo the most recent change
  cloop loop undo 123

  # Show result in table format
  cloop loop undo 123 --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    undo_parser.add_argument("id", type=int, help="Loop ID")
    add_format_option(undo_parser)

    # loop metrics
    metrics_parser = loop_subparsers.add_parser(
        "metrics",
        help="Show operational metrics for loop health",
        description="Display SLIs including status counts, stale loops, enrichment health.",
        epilog="""
Examples:
  cloop loop metrics
  cloop loop metrics --format json
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    add_format_option(metrics_parser)


def add_suggestion_parser(subparsers: Any) -> None:
    """Add 'suggestion' command parser."""
    from argparse import RawDescriptionHelpFormatter

    suggestion_parser = subparsers.add_parser(
        "suggestion",
        help="Manage AI suggestions",
        description="List, apply, or reject AI-generated loop suggestions",
    )
    suggestion_subparsers = suggestion_parser.add_subparsers(dest="suggestion_cmd", required=True)

    # suggestion list
    list_parser = suggestion_subparsers.add_parser(
        "list",
        help="List suggestions",
        description="List loop suggestions with optional filtering",
        epilog="""
Examples:
  # List all suggestions for a loop
  cloop suggestion list --loop-id 123

  # List only pending suggestions
  cloop suggestion list --pending

  # List all pending across all loops
  cloop suggestion list --pending --limit 100
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    list_parser.add_argument("--loop-id", type=int, help="Filter by loop ID")
    list_parser.add_argument("--pending", action="store_true", help="Show only pending suggestions")
    list_parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    add_format_option(list_parser)

    # suggestion show
    show_parser = suggestion_subparsers.add_parser(
        "show",
        help="Show suggestion details",
        description="Display detailed information about a suggestion",
        epilog="""
Examples:
  # Show suggestion details
  cloop suggestion show 456
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    show_parser.add_argument("id", type=int, help="Suggestion ID")
    add_format_option(show_parser)

    # suggestion apply
    apply_parser = suggestion_subparsers.add_parser(
        "apply",
        help="Apply suggestion",
        description="Apply a suggestion to its loop",
        epilog="""
Examples:
  # Apply all suggested fields above threshold
  cloop suggestion apply 456

  # Apply specific fields only
  cloop suggestion apply 456 --fields title,tags
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    apply_parser.add_argument("id", type=int, help="Suggestion ID")
    apply_parser.add_argument(
        "--fields",
        type=str,
        help="Comma-separated fields to apply (default: all above threshold)",
    )
    add_format_option(apply_parser)

    # suggestion reject
    reject_parser = suggestion_subparsers.add_parser(
        "reject",
        help="Reject suggestion",
        description="Reject a suggestion without applying any fields",
        epilog="""
Examples:
  # Reject a suggestion
  cloop suggestion reject 456
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    reject_parser.add_argument("id", type=int, help="Suggestion ID")
    add_format_option(reject_parser)
