"""CLI parser construction for the public `cloop` command.

Purpose:
    Build the canonical argparse tree for the packaged CLI without mixing in
    command-dispatch concerns.

Responsibilities:
    - Define the root parser metadata and help text
    - Register every top-level CLI command parser in one ordered place
    - Keep parser construction reusable for tests and external entrypoints

Scope:
    - Argparse parser creation only
    - Top-level parser registration order and public help surface

Non-scope:
    - Parsed-argument dispatch
    - Database initialization
    - Command handler business logic

Usage:
    - Import `build_parser()` from `cloop.cli_package.main` or this module when
      a caller needs the full CLI parser tree.

Invariants/Assumptions:
    - The registration order here defines the public CLI help ordering.
    - Parser builders own command-specific flags and nested subcommands.
    - Dispatching parsed arguments is handled separately in
      `cloop.cli_package.dispatch`.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from .._version import __version__
from .parsers.backup import add_backup_parser
from .parsers.chat import add_chat_parser
from .parsers.loop import add_loop_parser
from .parsers.loop_misc_parsers import (
    add_capture_parser,
    add_clarification_parser,
    add_export_parser,
    add_import_parser,
    add_inbox_parser,
    add_next_parser,
    add_projects_parser,
    add_suggestion_parser,
    add_tags_parser,
)
from .parsers.memory import add_memory_parser
from .parsers.plan import add_plan_parser
from .parsers.rag import add_ask_parser, add_ingest_parser
from .parsers.review import add_review_parser
from .parsers.template import add_template_parser
from .parsers.working_set import add_working_set_parser

ParserBuilder = Callable[[Any], None]

CLI_DESCRIPTION = "Cloop - Local-first AI knowledge base and task management"
CLI_EPILOG = """
Examples:
  # Loop lifecycle
  cloop capture "Buy groceries" --actionable
  cloop loop list --status inbox --format table
  cloop loop update 1 --next-action "Go to store" --due-at "2026-02-15T18:00:00Z"
  cloop loop close 1 --note "Done"

  # Query with DSL
  cloop loop search "status:inbox tag:work due:today"
  cloop loop search "due:on:2026-02-25"
  cloop loop search "due:between:2026-02-20..2026-02-28"
  cloop loop search "project:ClientAlpha blocked"
  cloop loop search "status:open groceries"
  cloop loop semantic-search "buy milk and eggs"

  # Grounded chat
  cloop chat "What should I focus on today?" --include-loop-context --include-memory-context
  cloop chat "Where is the onboarding checklist?" --include-rag-context --rag-scope onboarding

  # Memory management
  cloop memory create "User prefers dark mode" --category preference --priority 40
  cloop memory search "dark mode"

  # Saved views
  cloop loop view create --name "Today's tasks" --query "status:open due:today"
  cloop loop view list
  cloop loop view apply 1

  # Time tracking
  cloop loop timer start 1
  cloop loop timer status 1
  cloop loop timer stop 1 --notes "Completed the task"
  cloop loop sessions 1 --limit 10

  # Review cohorts
  cloop loop review                    # Show daily review cohorts
  cloop loop review --weekly           # Show weekly review cohorts
  cloop loop review --cohort stale     # Filter to stale loops only
  cloop loop review --all --format table  # All cohorts in table format

  # Checkpointed planning sessions
  cloop plan session create --name weekly-reset \
    --prompt "Build a checkpointed plan for my open launch work" \
    --query "status:open"
  cloop plan session execute --session 3

  # Working-set undo
  cloop working-set undo --event-id 42

  # Loop claims (multi-agent coordination)
  cloop loop claim 1 --owner agent-alpha
  cloop loop update 1 --title "Updated" --claim-token TOKEN
  cloop loop release 1 --token TOKEN
  cloop loop claims --owner agent-alpha

  # Data portability
  cloop export --output backup.json
  cloop import --file backup.json

  # Backup and restore
  cloop backup create --name daily
  cloop backup list
  cloop backup verify <backup-path>
  cloop backup restore <backup-path> --dry-run
  cloop backup restore <backup-path>
  cloop backup rotate --dry-run

Exit codes:
  0  success
  1  validation/input error
  2  not found or invalid transition
"""

TOP_LEVEL_PARSER_BUILDERS: tuple[ParserBuilder, ...] = (
    add_ingest_parser,
    add_ask_parser,
    add_chat_parser,
    add_capture_parser,
    add_inbox_parser,
    add_next_parser,
    add_loop_parser,
    add_template_parser,
    add_tags_parser,
    add_projects_parser,
    add_export_parser,
    add_import_parser,
    add_backup_parser,
    add_suggestion_parser,
    add_clarification_parser,
    add_review_parser,
    add_plan_parser,
    add_memory_parser,
    add_working_set_parser,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the complete public CLI parser tree."""
    parser = argparse.ArgumentParser(
        prog="cloop",
        description=CLI_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=CLI_EPILOG,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    for builder in TOP_LEVEL_PARSER_BUILDERS:
        builder(subparsers)
    return parser
