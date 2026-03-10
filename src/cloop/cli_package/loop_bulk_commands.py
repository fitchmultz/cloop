"""Loop bulk command handlers.

Purpose:
    CLI handlers for query-driven bulk loop operations.

Responsibilities:
    - Execute bulk update, close, and snooze on query-selected loops
    - Standardize preview/apply orchestration through shared helpers
    - Keep confirmation and preview rendering consistent across bulk commands

Non-scope:
    - Single-loop operations (see loop_core_commands.py)
    - Argument parsing (see parsers/loop.py)
"""

from __future__ import annotations

import sys
from datetime import timedelta
from re import match as re_match
from typing import Any, Callable

from ..loops import bulk as loop_bulk
from ..loops.models import format_utc_datetime, utc_now, validate_iso8601_timestamp
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_action, run_cli_db_action
from .output import emit_output


def parse_snooze_duration(duration: str) -> str | None:
    """Parse snooze duration. Supports: 30m, 1h, 2d, 1w, or ISO8601 timestamp."""
    try:
        return validate_iso8601_timestamp(duration, "snooze_until")
    except ValueError, TypeError:
        pass

    match = re_match(r"^(\d+)([mhdw])$", duration.strip())
    if not match:
        return None

    value, unit = int(match.group(1)), match.group(2)
    delta_map = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    return format_utc_datetime(utc_now() + timedelta(**{delta_map[unit]: value}))


def _prompt_confirm(message: str) -> bool:
    """Prompt user for confirmation."""
    try:
        response = input(f"{message} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return response in ("y", "yes")


def _render_preview(result: dict[str, Any], format_type: str, summary: str) -> None:
    targets = result.get("targets", [])
    print(f"\nMatched {len(targets)} loop(s):")
    emit_output(targets, format_type)
    if result.get("limited"):
        print(f"\nNote: Results limited to {result['matched_count']}. More matches may exist.")
    print(f"\n{summary}")


def _execute_bulk_operation(
    *,
    args: Any,
    settings: Settings,
    preview_operation: Any,
    apply_operation: Any,
    preview_summary: str,
    confirm_message: Callable[[int], str],
) -> int:
    preview_format = getattr(args, "format", "table")
    result_format = getattr(args, "format", "json")

    if args.dry_run:
        return run_cli_db_action(
            settings=settings,
            action=lambda conn: preview_operation(conn),
            render=lambda result: _render_preview(result, preview_format, preview_summary),
            error_handlers=[
                error_handler(
                    ValueError,
                    lambda exc: cli_error(str(exc), exit_code=2),
                )
            ],
        )

    preview_result: dict[str, Any] = {}

    def _preview(conn: Any) -> dict[str, Any]:
        nonlocal preview_result
        preview_result = preview_operation(conn)
        return preview_result

    preview_exit = run_cli_db_action(
        settings=settings,
        action=_preview,
        error_handlers=[
            error_handler(
                ValueError,
                lambda exc: cli_error(str(exc), exit_code=2),
            )
        ],
    )
    if preview_exit != 0:
        return preview_exit

    matched_count = preview_result.get("matched_count", 0)
    if (
        not args.confirm
        and matched_count > 0
        and not _prompt_confirm(confirm_message(matched_count))
    ):
        print("Aborted.")
        return 1

    def _render_result(result: dict[str, Any]) -> None:
        if result.get("limited"):
            print(
                f"Note: Operation limited to {args.limit} loops. More matches may exist.",
                file=sys.stderr,
            )
        emit_output(result, result_format)

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: apply_operation(conn),
        render=_render_result,
        error_handlers=[
            error_handler(
                ValueError,
                lambda exc: cli_error(str(exc), exit_code=2),
            )
        ],
        success_exit_code=0,
    )


def loop_bulk_update_command(args: Any, settings: Settings) -> int:
    """Handle 'loop bulk update' command."""
    fields: dict[str, Any] = {}
    if args.title:
        fields["title"] = args.title
    if args.project:
        fields["project"] = args.project
    if args.tags is not None:
        fields["tags"] = [tag.strip() for tag in args.tags.split(",")] if args.tags else []
    if args.urgency is not None:
        fields["urgency"] = args.urgency
    if args.importance is not None:
        fields["importance"] = args.importance

    if not fields:
        return run_cli_action(
            action=lambda: fail_cli("no fields specified for update", exit_code=2)
        )

    return _execute_bulk_operation(
        args=args,
        settings=settings,
        preview_operation=lambda conn: loop_bulk.query_bulk_update_loops(
            query=args.query,
            fields=fields,
            transactional=args.transactional,
            dry_run=True,
            limit=args.limit,
            conn=conn,
        ),
        apply_operation=lambda conn: loop_bulk.query_bulk_update_loops(
            query=args.query,
            fields=fields,
            transactional=args.transactional,
            dry_run=False,
            limit=args.limit,
            conn=conn,
        ),
        preview_summary="Dry-run complete. Run without --dry-run to apply changes.",
        confirm_message=lambda matched_count: f"Update {matched_count} loop(s)?",
    )


def loop_bulk_close_command(args: Any, settings: Settings) -> int:
    """Handle 'loop bulk close' command."""
    status = "dropped" if args.dropped else "completed"
    return _execute_bulk_operation(
        args=args,
        settings=settings,
        preview_operation=lambda conn: loop_bulk.query_bulk_close_loops(
            query=args.query,
            status=status,
            note=args.note,
            transactional=args.transactional,
            dry_run=True,
            limit=args.limit,
            conn=conn,
        ),
        apply_operation=lambda conn: loop_bulk.query_bulk_close_loops(
            query=args.query,
            status=status,
            note=args.note,
            transactional=args.transactional,
            dry_run=False,
            limit=args.limit,
            conn=conn,
        ),
        preview_summary=f"Dry-run complete. Would close as: {status}",
        confirm_message=lambda matched_count: f"Close {matched_count} loop(s) as {status}?",
    )


def loop_bulk_snooze_command(args: Any, settings: Settings) -> int:
    """Handle 'loop bulk snooze' command."""
    snooze_until = parse_snooze_duration(args.until)
    if snooze_until is None:
        return run_cli_action(
            action=lambda: fail_cli(f"invalid duration '{args.until}'", exit_code=2)
        )

    return _execute_bulk_operation(
        args=args,
        settings=settings,
        preview_operation=lambda conn: loop_bulk.query_bulk_snooze_loops(
            query=args.query,
            snooze_until_utc=snooze_until,
            transactional=args.transactional,
            dry_run=True,
            limit=args.limit,
            conn=conn,
        ),
        apply_operation=lambda conn: loop_bulk.query_bulk_snooze_loops(
            query=args.query,
            snooze_until_utc=snooze_until,
            transactional=args.transactional,
            dry_run=False,
            limit=args.limit,
            conn=conn,
        ),
        preview_summary=f"Dry-run complete. Would snooze until: {snooze_until}",
        confirm_message=lambda matched_count: f"Snooze {matched_count} loop(s)?",
    )
