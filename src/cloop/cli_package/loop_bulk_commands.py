"""Loop bulk command handlers.

Purpose:
    CLI handlers for query-driven bulk loop operations.

Responsibilities:
    - Execute bulk update/close/snooze on query-selected loops
    - Handle dry-run preview display
    - Prompt for confirmation before destructive operations
    - Format and output results

Non-scope:
    - Single-loop operations (see loop_commands.py)
    - Argument parsing (see parsers/loop.py)
"""

from __future__ import annotations

import sys
from typing import Any

from .. import db
from ..loops import service as loop_service
from ..loops.models import format_utc_datetime, utc_now
from ..settings import Settings
from .output import emit_output

try:
    from datetime import timedelta
    from re import match as re_match

    def parse_snooze_duration(duration: str) -> str | None:
        """Parse snooze duration. Supports: 30m, 1h, 2d, 1w, or ISO8601 timestamp."""
        from ..loops.models import validate_iso8601_timestamp

        try:
            return validate_iso8601_timestamp(duration, "snooze_until")
        except (ValueError, TypeError):
            pass

        match = re_match(r"^(\d+)([mhdw])$", duration.strip())
        if not match:
            return None

        value, unit = int(match.group(1)), match.group(2)
        delta_map = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
        delta = timedelta(**{delta_map[unit]: value})
        snooze_time = utc_now() + delta
        return format_utc_datetime(snooze_time)
except ImportError:
    # Fallback if import fails
    def parse_snooze_duration(duration: str) -> str | None:
        return None


def _prompt_confirm(message: str) -> bool:
    """Prompt user for confirmation."""
    try:
        response = input(f"{message} [y/N]: ").strip().lower()
        return response in ("y", "yes")
    except EOFError:
        return False


def _display_preview(targets: list[dict], format_type: str) -> None:
    """Display preview of matched loops."""
    print(f"\nMatched {len(targets)} loop(s):")
    emit_output(targets, format_type)


def loop_bulk_update_command(args: Any, settings: Settings) -> int:
    """Handle 'loop bulk update' command."""
    fields: dict[str, Any] = {}
    if args.title:
        fields["title"] = args.title
    if args.project:
        fields["project"] = args.project
    if args.tags is not None:
        fields["tags"] = [t.strip() for t in args.tags.split(",")] if args.tags else []
    if args.urgency is not None:
        fields["urgency"] = args.urgency
    if args.importance is not None:
        fields["importance"] = args.importance

    if not fields:
        print("Error: No fields specified for update", file=sys.stderr)
        return 2

    try:
        if args.dry_run:
            with db.core_connection(settings) as conn:
                result = loop_service.query_bulk_update_loops(
                    query=args.query,
                    fields=fields,
                    transactional=args.transactional,
                    dry_run=True,
                    limit=args.limit,
                    conn=conn,
                )
            targets = result.get("targets", [])
            _display_preview(targets, getattr(args, "format", "table"))
            if result.get("limited"):
                print(f"\nNote: Results limited to {args.limit}. More matches may exist.")
            print("\nDry-run complete. Run without --dry-run to apply changes.")
            return 0

        with db.core_connection(settings) as conn:
            preview = loop_service.query_bulk_update_loops(
                query=args.query,
                fields=fields,
                transactional=args.transactional,
                dry_run=True,
                limit=args.limit,
                conn=conn,
            )

        matched_count = preview.get("matched_count", 0)
        if not args.confirm and matched_count > 0:
            if not _prompt_confirm(f"Update {matched_count} loop(s)?"):
                print("Aborted.")
                return 1

        with db.core_connection(settings) as conn:
            result = loop_service.query_bulk_update_loops(
                query=args.query,
                fields=fields,
                transactional=args.transactional,
                dry_run=False,
                limit=args.limit,
                conn=conn,
            )

        if result.get("limited"):
            print(
                f"Note: Operation limited to {args.limit} loops. More matches may exist.",
                file=sys.stderr,
            )
        emit_output(result, getattr(args, "format", "json"))
        return 0 if result.get("ok") else 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def loop_bulk_close_command(args: Any, settings: Settings) -> int:
    """Handle 'loop bulk close' command."""
    status = "dropped" if args.dropped else "completed"

    try:
        if args.dry_run:
            with db.core_connection(settings) as conn:
                result = loop_service.query_bulk_close_loops(
                    query=args.query,
                    status=status,
                    note=args.note,
                    transactional=args.transactional,
                    dry_run=True,
                    limit=args.limit,
                    conn=conn,
                )
            targets = result.get("targets", [])
            _display_preview(targets, getattr(args, "format", "table"))
            if result.get("limited"):
                print(f"\nNote: Results limited to {args.limit}. More matches may exist.")
            print(f"\nDry-run complete. Would close as: {status}")
            return 0

        with db.core_connection(settings) as conn:
            preview = loop_service.query_bulk_close_loops(
                query=args.query,
                status=status,
                note=args.note,
                transactional=args.transactional,
                dry_run=True,
                limit=args.limit,
                conn=conn,
            )

        matched_count = preview.get("matched_count", 0)
        if not args.confirm and matched_count > 0:
            if not _prompt_confirm(f"Close {matched_count} loop(s) as {status}?"):
                print("Aborted.")
                return 1

        with db.core_connection(settings) as conn:
            result = loop_service.query_bulk_close_loops(
                query=args.query,
                status=status,
                note=args.note,
                transactional=args.transactional,
                dry_run=False,
                limit=args.limit,
                conn=conn,
            )

        if result.get("limited"):
            print(
                f"Note: Operation limited to {args.limit} loops. More matches may exist.",
                file=sys.stderr,
            )
        emit_output(result, getattr(args, "format", "json"))
        return 0 if result.get("ok") else 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


def loop_bulk_snooze_command(args: Any, settings: Settings) -> int:
    """Handle 'loop bulk snooze' command."""
    snooze_until = parse_snooze_duration(args.until)
    if snooze_until is None:
        print(f"Error: Invalid duration '{args.until}'", file=sys.stderr)
        return 2

    try:
        if args.dry_run:
            with db.core_connection(settings) as conn:
                result = loop_service.query_bulk_snooze_loops(
                    query=args.query,
                    snooze_until_utc=snooze_until,
                    transactional=args.transactional,
                    dry_run=True,
                    limit=args.limit,
                    conn=conn,
                )
            targets = result.get("targets", [])
            _display_preview(targets, getattr(args, "format", "table"))
            if result.get("limited"):
                print(f"\nNote: Results limited to {args.limit}. More matches may exist.")
            print(f"\nDry-run complete. Would snooze until: {snooze_until}")
            return 0

        with db.core_connection(settings) as conn:
            preview = loop_service.query_bulk_snooze_loops(
                query=args.query,
                snooze_until_utc=snooze_until,
                transactional=args.transactional,
                dry_run=True,
                limit=args.limit,
                conn=conn,
            )

        matched_count = preview.get("matched_count", 0)
        if not args.confirm and matched_count > 0:
            if not _prompt_confirm(f"Snooze {matched_count} loop(s)?"):
                print("Aborted.")
                return 1

        with db.core_connection(settings) as conn:
            result = loop_service.query_bulk_snooze_loops(
                query=args.query,
                snooze_until_utc=snooze_until,
                transactional=args.transactional,
                dry_run=False,
                limit=args.limit,
                conn=conn,
            )

        if result.get("limited"):
            print(
                f"Note: Operation limited to {args.limit} loops. More matches may exist.",
                file=sys.stderr,
            )
        emit_output(result, getattr(args, "format", "json"))
        return 0 if result.get("ok") else 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
