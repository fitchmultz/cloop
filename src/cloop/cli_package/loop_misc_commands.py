"""Loop misc command handlers.

Purpose:
    Implement CLI command handlers for miscellaneous loop operations.

Responsibilities:
    - Handle review, events, undo, metrics, tags, projects, export/import,
      suggestions, and clarifications
    - Normalize DB orchestration, expected error handling, and output emission
      through the shared CLI runtime

Non-scope:
    - Core loop CRUD operations
    - Scheduler operations
    - Claim operations
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from .. import db
from ..loops import enrichment_orchestration, enrichment_review, repo, service
from ..loops import events as loop_events
from ..loops import read_service as loop_read_service
from ..loops.errors import (
    ClarificationNotFoundError,
    LoopNotFoundError,
    SuggestionNotFoundError,
    UndoNotPossibleError,
    ValidationError,
)
from ..loops.models import utc_now
from ..schemas.export_import import ConflictPolicy, ExportFilters, ImportOptions
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_action, run_cli_db_action
from .output import emit_output


def _standard_error_handlers() -> list:
    return [
        error_handler(
            ValidationError,
            lambda exc: cli_error(exc.message),
        )
    ]


def loop_review_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop review' command."""
    from ..loops.review import compute_review_cohorts

    include_daily = args.daily or (not args.weekly)
    include_weekly = args.weekly or args.all

    def _action(conn: Any) -> dict[str, Any]:
        result = compute_review_cohorts(
            settings=settings,
            now_utc=utc_now(),
            conn=conn,
            include_daily=include_daily,
            include_weekly=include_weekly,
            limit_per_cohort=args.limit,
        )
        cohort_filter = getattr(args, "cohort", None)
        daily_results = result.daily
        weekly_results = result.weekly
        if cohort_filter:
            daily_results = [
                cohort for cohort in daily_results if cohort.cohort.value == cohort_filter
            ]
            weekly_results = [
                cohort for cohort in weekly_results if cohort.cohort.value == cohort_filter
            ]

        payload: dict[str, Any] = {"generated_at_utc": result.generated_at_utc}
        if include_daily and daily_results:
            payload["daily"] = [
                {"cohort": cohort.cohort.value, "count": cohort.count, "items": cohort.items}
                for cohort in daily_results
            ]
        if include_weekly and weekly_results:
            payload["weekly"] = [
                {"cohort": cohort.cohort.value, "count": cohort.count, "items": cohort.items}
                for cohort in weekly_results
            ]
        return payload

    return run_cli_db_action(
        settings=settings,
        action=_action,
        output_format=args.format,
    )


def loop_events_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop events' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_events.get_loop_events(
            loop_id=args.id,
            limit=args.limit,
            before_id=args.before,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopNotFoundError,
                lambda exc: cli_error(f"loop {exc.loop_id} not found", exit_code=2),
            )
        ],
    )


def loop_undo_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop undo' command."""
    from ..loops.errors import LoopClaimedError

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: (
            lambda result: {
                "loop": result["loop"],
                "undone_event_id": result["undone_event_id"],
                "undone_event_type": result["undone_event_type"],
            }
        )(
            loop_events.undo_last_event(
                loop_id=args.id,
                conn=conn,
            )
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopNotFoundError,
                lambda exc: cli_error(f"loop {exc.loop_id} not found", exit_code=2),
            ),
            error_handler(
                UndoNotPossibleError,
                lambda exc: cli_error(exc.message),
            ),
            error_handler(
                LoopClaimedError,
                lambda exc: cli_error(str(exc)),
            ),
        ],
    )


def loop_metrics_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop metrics' command."""
    from ..loops.metrics import compute_loop_metrics

    include_project = getattr(args, "project", False)
    include_trend = getattr(args, "trend", False)
    trend_window_days = getattr(args, "trend_window_days", 7)

    def _action(conn: Any) -> dict[str, Any]:
        metrics = compute_loop_metrics(
            conn=conn,
            now_utc=utc_now(),
            include_project_breakdown=include_project,
            include_trends=include_trend,
            trend_window_days=trend_window_days,
        )
        payload: dict[str, Any] = {
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
        if metrics.project_breakdown is not None:
            payload["project_breakdown"] = [
                {
                    "project_id": project.project_id,
                    "project_name": project.project_name,
                    "total_loops": project.total_loops,
                    "open_loops": project.open_loops,
                    "completed_loops": project.completed_loops,
                    "dropped_loops": project.dropped_loops,
                    "capture_count_window": project.capture_count_window,
                    "completion_count_window": project.completion_count_window,
                    "avg_age_open_hours": project.avg_age_open_hours,
                }
                for project in metrics.project_breakdown
            ]
        if metrics.trend_metrics is not None:
            payload["trend_metrics"] = {
                "window_days": metrics.trend_metrics.window_days,
                "points": [
                    {
                        "date": point.date,
                        "capture_count": point.capture_count,
                        "completion_count": point.completion_count,
                        "open_count": point.open_count,
                    }
                    for point in metrics.trend_metrics.points
                ],
                "total_captures": metrics.trend_metrics.total_captures,
                "total_completions": metrics.trend_metrics.total_completions,
                "avg_daily_captures": metrics.trend_metrics.avg_daily_captures,
                "avg_daily_completions": metrics.trend_metrics.avg_daily_completions,
            }
        return payload

    return run_cli_db_action(
        settings=settings,
        action=_action,
        output_format=args.format,
    )


def tags_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop tags' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_read_service.list_tags(conn=conn),
        output_format=args.format,
    )


def projects_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop projects' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: repo.list_projects(conn=conn),
        output_format=args.format,
    )


def export_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop export' command."""
    from ..loops.models import LoopStatus, parse_utc_datetime

    def _action() -> dict[str, Any]:
        filters = None
        if any(
            [
                args.status,
                args.project,
                args.tag,
                args.created_after,
                args.created_before,
                args.updated_after,
            ]
        ):
            status_list = None
            if args.status:
                try:
                    status_list = [LoopStatus(status).value for status in args.status]
                except ValueError as exc:
                    fail_cli(str(exc))

            filters = ExportFilters(
                status=status_list,
                project=args.project,
                tag=args.tag,
                created_after=parse_utc_datetime(args.created_after)
                if args.created_after
                else None,
                created_before=parse_utc_datetime(args.created_before)
                if args.created_before
                else None,
                updated_after=parse_utc_datetime(args.updated_after)
                if args.updated_after
                else None,
            )

        with db.core_connection(settings) as conn:
            loops = service.export_loops(conn=conn, filters=filters)

        return {"version": 1, "loops": loops, "filtered": filters is not None}

    def _render(payload: dict[str, Any]) -> None:
        if args.output:
            Path(args.output).write_text(json.dumps(payload, indent=2))
            print(f"Exported {len(payload['loops'])} loops to {args.output}")
            return
        emit_output(payload, args.format)

    return run_cli_action(
        action=_action,
        render=_render,
    )


def import_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop import' command."""
    from .. import db

    def _action() -> dict[str, Any]:
        try:
            raw_data = Path(args.file).read_text() if args.file else sys.stdin.read()
            data = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            fail_cli(f"invalid JSON: {exc}")

        loops = data.get("loops", data) if isinstance(data, dict) else data
        options = ImportOptions(
            dry_run=args.dry_run,
            conflict_policy=ConflictPolicy(args.conflict_policy),
        )

        with db.core_connection(settings) as conn:
            result = service.import_loops(loops=loops, conn=conn, options=options)

        output: dict[str, Any] = {
            "imported": result.imported,
            "skipped": result.skipped,
            "updated": result.updated,
            "conflicts_detected": result.conflicts_detected,
            "dry_run": result.dry_run,
        }
        if result.dry_run and result.preview:
            output["preview"] = {
                "total_loops": result.preview.total_loops,
                "would_create": result.preview.would_create,
                "would_skip": result.preview.would_skip,
                "would_update": result.preview.would_update,
                "conflicts": [
                    {
                        "existing_loop_id": conflict.existing_loop_id,
                        "match_field": conflict.match_field,
                        "raw_text": conflict.imported_loop.get("raw_text", ""),
                    }
                    for conflict in result.preview.conflicts
                ],
                "validation_errors": result.preview.validation_errors,
            }
        return output

    return run_cli_action(
        action=_action,
        output_format=args.format,
        error_handlers=[
            error_handler(
                ValidationError,
                lambda exc: cli_error(exc.message),
            )
        ],
    )


def suggestion_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion list' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_review.list_loop_suggestions(
            loop_id=args.loop_id,
            pending_only=args.pending,
            limit=args.limit,
            conn=conn,
        ),
        output_format=args.format,
    )


def suggestion_show_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion show' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_review.get_loop_suggestion(
            suggestion_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                SuggestionNotFoundError,
                lambda _exc: cli_error(f"suggestion {args.id} not found", exit_code=2),
            )
        ],
    )


def suggestion_apply_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion apply' command."""
    fields = args.fields.split(",") if args.fields else None
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_review.apply_suggestion(
            suggestion_id=args.id,
            fields=fields,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                SuggestionNotFoundError,
                lambda _exc: cli_error(f"suggestion {args.id} not found", exit_code=2),
            ),
            *_standard_error_handlers(),
        ],
    )


def suggestion_reject_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop suggestion reject' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_review.reject_suggestion(
            suggestion_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                SuggestionNotFoundError,
                lambda _exc: cli_error(f"suggestion {args.id} not found", exit_code=2),
            ),
            *_standard_error_handlers(),
        ],
    )


def clarification_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop clarification list' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_review.list_loop_clarifications(
            loop_id=args.loop_id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopNotFoundError,
                lambda _exc: cli_error(f"loop {args.loop_id} not found", exit_code=2),
            )
        ],
    )


def clarification_answer_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop clarification answer' command."""
    answer_input = enrichment_review.ClarificationAnswerInput(
        clarification_id=args.id,
        answer=args.answer,
    )
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_review.submit_clarification_answers(
            loop_id=args.loop_id,
            answers=[answer_input],
            conn=conn,
        ).to_payload(),
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopNotFoundError,
                lambda _exc: cli_error(f"loop {args.loop_id} not found", exit_code=2),
            ),
            error_handler(
                ClarificationNotFoundError,
                lambda _exc: cli_error(f"clarification {args.id} not found", exit_code=2),
            ),
            *_standard_error_handlers(),
        ],
    )


def clarification_answer_many_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop clarification answer-many' command."""

    def _parse_item(item: str) -> enrichment_review.ClarificationAnswerInput:
        clarification_text, separator, answer = item.partition("=")
        if not separator:
            fail_cli(f"invalid --item value '{item}' (expected <clarification_id>=<answer>)")
        try:
            clarification_id = int(clarification_text)
        except ValueError:
            fail_cli(f"invalid clarification id in --item value '{item}' (expected integer id)")
        if not answer.strip():
            fail_cli(f"invalid --item value '{item}' (answer must not be empty)")
        return enrichment_review.ClarificationAnswerInput(
            clarification_id=clarification_id,
            answer=answer,
        )

    answer_inputs = [_parse_item(item) for item in args.item]
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_review.submit_clarification_answers(
            loop_id=args.loop_id,
            answers=answer_inputs,
            conn=conn,
        ).to_payload(),
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopNotFoundError,
                lambda _exc: cli_error(f"loop {args.loop_id} not found", exit_code=2),
            ),
            error_handler(
                ClarificationNotFoundError,
                lambda exc: cli_error(
                    f"clarification {exc.clarification_id} not found",
                    exit_code=2,
                ),
            ),
            *_standard_error_handlers(),
        ],
    )


def clarification_refine_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop clarification refine' command."""

    def _parse_item(item: str) -> enrichment_review.ClarificationAnswerInput:
        clarification_text, separator, answer = item.partition("=")
        if not separator:
            fail_cli(f"invalid --item value '{item}' (expected <clarification_id>=<answer>)")
        try:
            clarification_id = int(clarification_text)
        except ValueError:
            fail_cli(f"invalid clarification id in --item value '{item}' (expected integer id)")
        if not answer.strip():
            fail_cli(f"invalid --item value '{item}' (answer must not be empty)")
        return enrichment_review.ClarificationAnswerInput(
            clarification_id=clarification_id,
            answer=answer,
        )

    answer_inputs = [_parse_item(item) for item in args.item]
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: enrichment_orchestration.orchestrate_clarification_refinement(
            loop_id=args.loop_id,
            answers=answer_inputs,
            conn=conn,
            settings=settings,
        ).to_payload(),
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopNotFoundError,
                lambda _exc: cli_error(f"loop {args.loop_id} not found", exit_code=2),
            ),
            error_handler(
                ClarificationNotFoundError,
                lambda exc: cli_error(
                    f"clarification {exc.clarification_id} not found",
                    exit_code=2,
                ),
            ),
            *_standard_error_handlers(),
        ],
    )
