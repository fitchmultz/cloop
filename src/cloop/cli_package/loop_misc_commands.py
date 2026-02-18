"""Loop misc command handlers.

Purpose:
    Implement CLI command handlers for miscellaneous loop operations.

Responsibilities:
    - Handle review, events, undo, metrics, tags, projects, export, import, suggestions

Non-scope:
    - Does not implement core loop CRUD (in separate command modules)
    - Does not manage scheduler operations (separate scheduler module)
    - Does not handle claim operations (in loop_claim_commands module)
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from typing import Any

from .. import db
from ..loops import repo, service
from ..loops.errors import LoopNotFoundError, UndoNotPossibleError, ValidationError
from ..loops.models import utc_now
from ..settings import Settings
from .output import emit_output


def loop_review_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop review' command."""
    from ..loops.review import compute_review_cohorts

    include_daily = args.daily or (not args.weekly)  # Default to daily if neither specified
    include_weekly = args.weekly or args.all

    with db.core_connection(settings) as conn:
        result = compute_review_cohorts(
            settings=settings,
            now_utc=utc_now(),
            conn=conn,
            include_daily=include_daily,
            include_weekly=include_weekly,
            limit_per_cohort=args.limit,
        )

    # Filter by specific cohort if requested
    cohort_filter = getattr(args, "cohort", None)
    daily_results = result.daily
    weekly_results = result.weekly
    if cohort_filter:
        daily_results = [c for c in daily_results if c.cohort.value == cohort_filter]
        weekly_results = [c for c in weekly_results if c.cohort.value == cohort_filter]

    output: dict[str, Any] = {
        "generated_at_utc": result.generated_at_utc,
    }

    if include_daily and daily_results:
        output["daily"] = [
            {"cohort": c.cohort.value, "count": c.count, "items": c.items} for c in daily_results
        ]

    if include_weekly and weekly_results:
        output["weekly"] = [
            {"cohort": c.cohort.value, "count": c.count, "items": c.items} for c in weekly_results
        ]

    emit_output(output, args.format)
    return 0


def loop_events_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop events' command."""
    try:
        with db.core_connection(settings) as conn:
            events = service.get_loop_events(
                loop_id=args.id,
                limit=args.limit,
                before_id=args.before,
                conn=conn,
            )
        emit_output(events, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


def loop_undo_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop undo' command."""
    from ..loops.errors import LoopClaimedError

    try:
        with db.core_connection(settings) as conn:
            result = service.undo_last_event(
                loop_id=args.id,
                conn=conn,
            )
        output = {
            "loop": result["loop"],
            "undone_event_id": result["undone_event_id"],
            "undone_event_type": result["undone_event_type"],
        }
        emit_output(output, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except UndoNotPossibleError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 1
    except LoopClaimedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_metrics_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop metrics' command."""
    from ..loops.metrics import compute_loop_metrics

    with db.core_connection(settings) as conn:
        metrics = compute_loop_metrics(conn=conn, now_utc=utc_now())

    output = {
        "generated_at_utc": metrics.generated_at_utc,
        "total_loops": metrics.total_loops,
        "status_counts": {
            "inbox": metrics.status_counts.inbox,
            "actionable": metrics.status_counts.actionable,
            "blocked": metrics.status_counts.blocked,
            "scheduled": metrics.status_counts.scheduled,
            "completed": metrics.status_counts.completed,
            "dropped": metrics.status_counts.dropped,
        },
        "health_indicators": {
            "stale_open_count": metrics.stale_open_count,
            "blocked_too_long_count": metrics.blocked_too_long_count,
            "no_next_action_count": metrics.no_next_action_count,
            "enrichment_pending_count": metrics.enrichment_pending_count,
            "enrichment_failed_count": metrics.enrichment_failed_count,
        },
        "throughput_24h": {
            "captures": metrics.capture_count_24h,
            "completions": metrics.completion_count_24h,
        },
        "avg_age_open_hours": metrics.avg_age_open_hours,
    }
    emit_output(output, args.format)
    return 0


def tags_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop tags' command."""
    with db.core_connection(settings) as conn:
        tags = service.list_tags(conn=conn)
    emit_output(tags, args.format)
    return 0


def projects_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop projects' command."""
    with db.core_connection(settings) as conn:
        projects = repo.list_projects(conn=conn)
    emit_output(projects, args.format)
    return 0


def export_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop export' command."""
    with db.core_connection(settings) as conn:
        loops = service.export_loops(conn=conn)
    payload = {"version": 1, "loops": loops}
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(json.dumps(payload, indent=2))
        print(f"Exported {len(loops)} loops to {args.output}", file=sys.stderr)
    else:
        emit_output(payload, args.format)
    return 0


def import_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop import' command."""
    try:
        if args.file:
            from pathlib import Path

            data = json.loads(Path(args.file).read_text())
        else:
            data = json.loads(sys.stdin.read())

        loops = data.get("loops", data) if isinstance(data, dict) else data

        with db.core_connection(settings) as conn:
            imported = service.import_loops(loops=loops, conn=conn)

        emit_output({"imported": imported}, args.format)
        return 0
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def suggestion_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion list' command."""
    with db.core_connection(settings) as conn:
        suggestions = service.list_loop_suggestions(
            loop_id=args.loop_id,
            pending_only=args.pending,
            limit=args.limit,
            conn=conn,
        )
    emit_output(suggestions, args.format)
    return 0


def suggestion_show_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion show' command."""
    with db.core_connection(settings) as conn:
        suggestion = repo.read_loop_suggestion(suggestion_id=args.id, conn=conn)

    if not suggestion:
        print(f"error: suggestion {args.id} not found", file=sys.stderr)
        return 2

    # Parse and pretty-print the suggestion_json
    suggestion["parsed"] = json.loads(suggestion["suggestion_json"])
    emit_output(suggestion, args.format)
    return 0


def suggestion_apply_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion apply' command."""
    from ..loops.errors import SuggestionNotFoundError

    fields = args.fields.split(",") if args.fields else None

    try:
        with db.core_connection(settings) as conn:
            result = service.apply_suggestion(
                suggestion_id=args.id,
                fields=fields,
                conn=conn,
                settings=settings,
            )
        emit_output(result, args.format)
        return 0
    except SuggestionNotFoundError:
        print(f"error: suggestion {args.id} not found", file=sys.stderr)
        return 2
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def suggestion_reject_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion reject' command."""
    from ..loops.errors import SuggestionNotFoundError

    try:
        with db.core_connection(settings) as conn:
            result = service.reject_suggestion(suggestion_id=args.id, conn=conn)
        emit_output(result, args.format)
        return 0
    except SuggestionNotFoundError:
        print(f"error: suggestion {args.id} not found", file=sys.stderr)
        return 2
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
