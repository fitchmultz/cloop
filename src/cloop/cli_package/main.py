"""Command-line interface for Cloop loop and retrieval workflows.

Purpose:
    Provide a local-first CLI for ingestion, retrieval, and full loop lifecycle management.

Responsibilities:
    - Parse CLI arguments and route to service-layer functions.
    - Initialize database connections.
    - Normalize output for automation (`json`) and human review (`table`).
    - Convert domain errors into stable process exit codes.

Non-scope:
    - Business-rule validation and persistence logic (owned by service/repo layers).
    - HTTP transport concerns (owned by FastAPI routes).
    - Output formatting (see cli/output.py).
    - Command implementations (see cli/*_commands.py).

Invariants/assumptions:
    - Exit code `0` means success.
    - Exit code `1` means validation/input errors.
    - Exit code `2` means missing resources or invalid state transitions.
"""

from __future__ import annotations

import argparse
from typing import List

from .. import db
from .._version import __version__
from ..settings import Settings, get_settings

# Import command handlers
from .backup_commands import (
    backup_create_command,
    backup_list_command,
    backup_restore_command,
    backup_rotate_command,
    backup_verify_command,
)
from .loop_bulk_commands import (
    loop_bulk_close_command,
    loop_bulk_snooze_command,
    loop_bulk_update_command,
)
from .loop_claim_commands import (
    loop_claim_command,
    loop_force_release_claim_command,
    loop_get_claim_command,
    loop_list_claims_command,
    loop_release_claim_command,
    loop_renew_claim_command,
)
from .loop_core_commands import (
    capture_command,
    inbox_command,
    loop_close_command,
    loop_enrich_command,
    loop_get_command,
    loop_list_command,
    loop_search_command,
    loop_snooze_command,
    loop_status_command,
    loop_update_command,
    next_command,
)
from .loop_dep_commands import loop_dep_command
from .loop_misc_commands import (
    export_command,
    import_command,
    loop_events_command,
    loop_metrics_command,
    loop_review_command,
    loop_undo_command,
    projects_command,
    suggestion_apply_command,
    suggestion_list_command,
    suggestion_reject_command,
    suggestion_show_command,
    tags_command,
)
from .loop_timer_commands import sessions_command, timer_command
from .loop_view_commands import (
    loop_view_apply_command,
    loop_view_create_command,
    loop_view_delete_command,
    loop_view_get_command,
    loop_view_list_command,
    loop_view_update_command,
)

# Import parser builders
from .parsers.backup import add_backup_parser
from .parsers.loop import add_loop_parser
from .parsers.loop_misc_parsers import (
    add_capture_parser,
    add_export_parser,
    add_import_parser,
    add_inbox_parser,
    add_next_parser,
    add_projects_parser,
    add_suggestion_parser,
    add_tags_parser,
)
from .parsers.rag import add_ask_parser, add_ingest_parser
from .parsers.template import add_template_parser
from .rag_commands import ask_command, ingest_command
from .template_commands import (
    template_create_command,
    template_delete_command,
    template_from_loop_command,
    template_list_command,
    template_show_command,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the complete argument parser."""
    parser = argparse.ArgumentParser(
        prog="cloop",
        description="Cloop - Local-first AI knowledge base and task management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
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
        """,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_ingest_parser(subparsers)
    add_ask_parser(subparsers)
    add_capture_parser(subparsers)
    add_inbox_parser(subparsers)
    add_next_parser(subparsers)

    add_loop_parser(subparsers)
    add_template_parser(subparsers)

    add_tags_parser(subparsers)
    add_projects_parser(subparsers)
    add_export_parser(subparsers)
    add_import_parser(subparsers)
    add_backup_parser(subparsers)
    add_suggestion_parser(subparsers)

    return parser


def main(argv: List[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    settings: Settings = get_settings()

    db.init_databases(settings)

    # Route to handlers
    if args.command == "ingest":
        return ingest_command(args, settings)
    if args.command == "ask":
        return ask_command(args, settings)
    if args.command == "capture":
        return capture_command(args, settings)
    if args.command == "inbox":
        return inbox_command(args, settings)
    if args.command == "next":
        return next_command(args, settings)

    if args.command == "loop":
        if args.loop_command == "get":
            return loop_get_command(args, settings)
        if args.loop_command == "list":
            return loop_list_command(args, settings)
        if args.loop_command == "search":
            return loop_search_command(args, settings)
        if args.loop_command == "update":
            return loop_update_command(args, settings)
        if args.loop_command == "status":
            return loop_status_command(args, settings)
        if args.loop_command == "close":
            return loop_close_command(args, settings)
        if args.loop_command == "enrich":
            return loop_enrich_command(args, settings)
        if args.loop_command == "snooze":
            return loop_snooze_command(args, settings)
        if args.loop_command == "view":
            if args.view_command == "create":
                return loop_view_create_command(args, settings)
            if args.view_command == "list":
                return loop_view_list_command(args, settings)
            if args.view_command == "get":
                return loop_view_get_command(args, settings)
            if args.view_command == "update":
                return loop_view_update_command(args, settings)
            if args.view_command == "delete":
                return loop_view_delete_command(args, settings)
            if args.view_command == "apply":
                return loop_view_apply_command(args, settings)
            parser.error(f"Unknown view command: {args.view_command}")
            return 2
        if args.loop_command == "claim":
            return loop_claim_command(args, settings)
        if args.loop_command == "renew":
            return loop_renew_claim_command(args, settings)
        if args.loop_command == "release":
            return loop_release_claim_command(args, settings)
        if args.loop_command == "get-claim":
            return loop_get_claim_command(args, settings)
        if args.loop_command == "claims":
            return loop_list_claims_command(args, settings)
        if args.loop_command == "force-release":
            return loop_force_release_claim_command(args, settings)
        if args.loop_command == "dep":
            return loop_dep_command(args, settings)
        if args.loop_command == "timer":
            return timer_command(args, settings)
        if args.loop_command == "sessions":
            return sessions_command(args, settings)
        if args.loop_command == "review":
            return loop_review_command(args, settings)
        if args.loop_command == "events":
            return loop_events_command(args, settings)
        if args.loop_command == "undo":
            return loop_undo_command(args, settings)
        if args.loop_command == "metrics":
            return loop_metrics_command(args, settings)
        if args.loop_command == "bulk":
            if args.bulk_action == "update":
                return loop_bulk_update_command(args, settings)
            if args.bulk_action == "close":
                return loop_bulk_close_command(args, settings)
            if args.bulk_action == "snooze":
                return loop_bulk_snooze_command(args, settings)
            parser.error(f"Unknown bulk action: {args.bulk_action}")
        parser.error(f"Unknown loop command: {args.loop_command}")

    if args.command == "template":
        if args.template_command == "list":
            return template_list_command(args, settings)
        if args.template_command == "show":
            return template_show_command(args, settings)
        if args.template_command == "create":
            return template_create_command(args, settings)
        if args.template_command == "delete":
            return template_delete_command(args, settings)
        if args.template_command == "from-loop":
            return template_from_loop_command(args, settings)
        parser.error(f"Unknown template command: {args.template_command}")
        return 2

    if args.command == "tags":
        return tags_command(args, settings)
    if args.command == "projects":
        return projects_command(args, settings)
    if args.command == "export":
        return export_command(args, settings)
    if args.command == "import":
        return import_command(args, settings)
    if args.command == "backup":
        if args.backup_command == "create":
            return backup_create_command(args, settings)
        if args.backup_command == "restore":
            return backup_restore_command(args, settings)
        if args.backup_command == "list":
            return backup_list_command(args, settings)
        if args.backup_command == "verify":
            return backup_verify_command(args, settings)
        if args.backup_command == "rotate":
            return backup_rotate_command(args, settings)
        parser.error(f"Unknown backup command: {args.backup_command}")
        return 2

    if args.command == "suggestion":
        if args.suggestion_cmd == "list":
            return suggestion_list_command(args, settings)
        elif args.suggestion_cmd == "show":
            return suggestion_show_command(args, settings)
        elif args.suggestion_cmd == "apply":
            return suggestion_apply_command(args, settings)
        elif args.suggestion_cmd == "reject":
            return suggestion_reject_command(args, settings)
        parser.error(f"Unknown suggestion command: {args.suggestion_cmd}")
        return 2

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
