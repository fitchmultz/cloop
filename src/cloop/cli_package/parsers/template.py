"""Template command argument parsers.

Purpose:
    Argument parsers for template commands.
"""

from __future__ import annotations

from typing import Any

from .base import add_format_option


def add_template_parser(subparsers: Any) -> None:
    """Add 'template' command and subcommand parsers."""
    from argparse import RawDescriptionHelpFormatter

    template_parser = subparsers.add_parser(
        "template",
        help="Manage loop templates",
    )
    template_sub = template_parser.add_subparsers(dest="template_command", required=True)

    # template list
    list_parser = template_sub.add_parser(
        "list",
        help="List all templates",
        description="List all loop templates",
        epilog="""
Examples:
  # List templates as JSON
  cloop template list

  # List templates in table format
  cloop template list --format table
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    add_format_option(list_parser)

    # template show
    show_parser = template_sub.add_parser(
        "show",
        help="Show template details",
        description="Show detailed information about a template",
        epilog="""
Examples:
  # Show template by name
  cloop template show "Weekly report"

  # Show template by ID
  cloop template show 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    show_parser.add_argument("name_or_id", help="Template name or ID")
    add_format_option(show_parser)

    # template create
    create_parser = template_sub.add_parser(
        "create",
        help="Create a template",
        description="Create a reusable loop template with default values",
        epilog="""
Examples:
  # Basic template
  cloop template create "Weekly report" --pattern "Weekly report for"

  # Template with defaults
  cloop template create "Meeting" --pattern "Meeting:" --tags "meetings,work" --actionable

  # Template with time estimate
  cloop template create "Code review" --pattern "Review PR" --time 30 --actionable
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    create_parser.add_argument("name", help="Template name")
    create_parser.add_argument("--description", "-d", help="Template description")
    create_parser.add_argument("--pattern", "-p", default="", help="Raw text pattern")
    create_parser.add_argument("--tags", help="Comma-separated default tags")
    create_parser.add_argument("--time", type=int, help="Default time estimate (minutes)")
    create_parser.add_argument("--actionable", action="store_true", help="Default to actionable")
    add_format_option(create_parser)

    # template delete
    delete_parser = template_sub.add_parser(
        "delete",
        help="Delete a template",
        description="Delete a template by name or ID",
        epilog="""
Examples:
  # Delete template by name
  cloop template delete "Old template"

  # Delete template by ID
  cloop template delete 123
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    delete_parser.add_argument("name_or_id", help="Template name or ID")

    # template from-loop
    from_loop_parser = template_sub.add_parser(
        "from-loop",
        help="Create template from loop",
        description="Create a new template based on an existing loop",
        epilog="""
Examples:
  # Create template from loop
  cloop template from-loop 123 "My template"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    from_loop_parser.add_argument("loop_id", type=int, help="Loop ID")
    from_loop_parser.add_argument("name", help="Template name")
    add_format_option(from_loop_parser)
