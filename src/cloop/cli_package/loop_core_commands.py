"""Loop core command handlers.

Purpose:
    Implement CLI command handlers for core loop operations.

Responsibilities:
    - Handle capture, inbox, next, get, list, search, semantic-search, update,
      status, close, enrich, snooze commands

Non-scope:
    - Does not handle dependency operations (see loop_dep_commands.py)
    - Does not handle timer operations (see loop_timer_commands.py)
    - Does not handle view operations (see loop_view_commands.py)
"""

from __future__ import annotations

import json
import logging
import re
from argparse import Namespace
from datetime import datetime, timedelta
from typing import Any

from ..loops import read_service as loop_read_service
from ..loops import service as loop_service
from ..loops.capture_orchestration import (
    CaptureFieldInputs,
    CaptureOrchestrationInput,
    CaptureStatusFlags,
    CaptureTemplateRef,
    orchestrate_capture,
)
from ..loops.enrichment_orchestration import orchestrate_loop_enrichment
from ..loops.errors import (
    ClaimNotFoundError,
    DependencyCycleError,
    DependencyNotMetError,
    LoopClaimedError,
    LoopNotFoundError,
    TransitionError,
    ValidationError,
)
from ..loops.models import (
    LoopStatus,
    format_utc_datetime,
    utc_now,
    validate_iso8601_timestamp,
)
from ..loops.utils import normalize_tags
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_action, run_cli_db_action
from .output import emit_output

logger = logging.getLogger(__name__)

_OPEN_STATUSES = [
    LoopStatus.INBOX,
    LoopStatus.ACTIONABLE,
    LoopStatus.BLOCKED,
    LoopStatus.SCHEDULED,
]


def _emit_json(result: Any) -> None:
    """Emit JSON output with the legacy indentation used by loop CLI commands."""
    print(json.dumps(result, indent=2))


def _loop_not_found_handler(*, loop_id: int) -> list:
    return [
        error_handler(
            LoopNotFoundError,
            lambda _exc: cli_error(f"loop {loop_id} not found", exit_code=2),
        )
    ]


def _claim_error_handlers(*, loop_id: int) -> list:
    return [
        *_loop_not_found_handler(loop_id=loop_id),
        error_handler(
            LoopClaimedError,
            lambda exc: cli_error(str(exc)),
        ),
        error_handler(
            ClaimNotFoundError,
            lambda _exc: cli_error("invalid or expired claim token"),
        ),
    ]


def _transition_error_handlers(*, loop_id: int) -> list:
    return [
        *_claim_error_handlers(loop_id=loop_id),
        error_handler(
            TransitionError,
            lambda exc: cli_error(str(exc), exit_code=2),
        ),
        error_handler(
            DependencyNotMetError,
            lambda exc: cli_error(
                f"{exc.message} (open dependencies: {exc.open_dependencies})",
                exit_code=2,
            ),
        ),
        error_handler(
            DependencyCycleError,
            lambda exc: cli_error(exc.message, exit_code=2),
        ),
    ]


def parse_list_status_filter(raw_status: str | None) -> list[LoopStatus] | None:
    """Parse status filter for loop list command."""
    if raw_status is None or raw_status == "all":
        return None
    if raw_status == "open":
        return _OPEN_STATUSES
    try:
        return [LoopStatus(raw_status)]
    except ValueError:
        status_values = ", ".join(
            ["open", "all", "inbox", "actionable", "blocked", "scheduled", "completed", "dropped"]
        )
        raise ValueError(
            f"invalid status '{raw_status}' (expected one of: {status_values})"
        ) from None


def capture_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop capture' command."""
    local_now = datetime.now().astimezone()
    captured_at = args.captured_at or local_now.isoformat(timespec="seconds")
    tz_offset_min = args.tz_offset_min
    if tz_offset_min is None:
        offset = local_now.utcoffset()
        tz_offset_min = int(offset.total_seconds() / 60) if offset else 0

    template_ref = CaptureTemplateRef()
    if getattr(args, "template", None):
        try:
            template_ref = CaptureTemplateRef(template_id=int(args.template))
        except ValueError:
            template_ref = CaptureTemplateRef(template_name=args.template)

    input_data = CaptureOrchestrationInput(
        raw_text=args.text,
        captured_at_iso=captured_at,
        client_tz_offset_min=tz_offset_min,
        status_flags=CaptureStatusFlags(
            actionable=args.actionable,
            blocked=args.blocked,
            scheduled=args.scheduled,
        ),
        schedule=getattr(args, "schedule", None),
        rrule=getattr(args, "rrule", None),
        timezone=getattr(args, "timezone", None),
        template_ref=template_ref,
        field_inputs=CaptureFieldInputs(
            activation_energy=getattr(args, "activation_energy", None),
            due_at_utc=getattr(args, "due", None),
            next_action=getattr(args, "next_action", None),
            project=getattr(args, "project", None),
            tags=getattr(args, "tags", None),
            time_minutes=getattr(args, "time_minutes", None),
        ),
    )

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: (
            orchestrate_capture(
                input_data=input_data,
                settings=settings,
                conn=conn,
            ).loop
        ),
        render=_emit_json,
        error_handlers=[
            error_handler(
                ValidationError,
                lambda exc: cli_error(
                    exc.message,
                    exit_code=2 if exc.field in {"template_id", "template_name"} else 1,
                ),
            )
        ],
    )


def inbox_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop inbox' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_read_service.list_loops(
            status=LoopStatus.INBOX,
            limit=args.limit,
            offset=0,
            conn=conn,
        ),
        render=_emit_json,
    )


def next_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop next' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_read_service.next_loops(limit=args.limit, conn=conn),
        render=_emit_json,
    )


def loop_get_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop get' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_read_service.get_loop(loop_id=args.id, conn=conn),
        output_format=args.format,
        error_handlers=_loop_not_found_handler(loop_id=args.id),
    )


def loop_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop list' command."""
    try:
        statuses = parse_list_status_filter(args.status)
    except ValueError as exc:
        message = str(exc)
        return run_cli_action(action=lambda: fail_cli(message))

    def _list(conn: Any) -> list[dict[str, Any]]:
        if args.tag:
            return loop_read_service.list_loops_by_tag(
                tag=args.tag,
                statuses=statuses,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        if statuses is None:
            return loop_read_service.list_loops(
                status=None,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        if len(statuses) == 1:
            return loop_read_service.list_loops(
                status=statuses[0],
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        return loop_read_service.list_loops_by_statuses(
            statuses=statuses,
            limit=args.limit,
            offset=args.offset,
            conn=conn,
        )

    return run_cli_db_action(
        settings=settings,
        action=_list,
        output_format=args.format,
    )


def loop_search_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop search' command."""
    positional_query = args.query
    flag_query = args.query_flag
    if positional_query and flag_query:
        return run_cli_action(
            action=lambda: fail_cli("provide either positional query or --query, not both")
        )
    query = flag_query or positional_query
    if not query:
        return run_cli_action(
            action=lambda: fail_cli("missing query (use positional value or --query)")
        )

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_read_service.search_loops_by_query(
            query=query,
            limit=args.limit,
            offset=args.offset,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                ValidationError,
                lambda exc: cli_error(str(exc)),
            )
        ],
    )


def loop_semantic_search_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop semantic-search' command."""
    try:
        statuses = parse_list_status_filter(args.status)
    except ValueError as exc:
        message = str(exc)
        return run_cli_action(action=lambda: fail_cli(message))

    positional_query = args.query
    flag_query = args.query_flag
    if positional_query and flag_query:
        return run_cli_action(
            action=lambda: fail_cli("provide either positional query or --query, not both")
        )
    query = flag_query or positional_query
    if not query:
        return run_cli_action(
            action=lambda: fail_cli("missing query (use positional value or --query)")
        )

    def _render(result: dict[str, Any]) -> None:
        if args.format == "json":
            _emit_json(result)
            return
        emit_output(result["items"], args.format)

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_read_service.semantic_search_loops(
            query=query,
            statuses=statuses,
            limit=args.limit,
            offset=args.offset,
            min_score=args.min_score,
            conn=conn,
            settings=settings,
        ),
        render=_render,
        error_handlers=[
            error_handler(
                ValidationError,
                lambda exc: cli_error(str(exc)),
            )
        ],
    )


def loop_update_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop update' command."""
    fields: dict[str, Any] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.summary is not None:
        fields["summary"] = args.summary
    if args.next_action is not None:
        fields["next_action"] = args.next_action
    if args.due_at is not None:
        fields["due_at_utc"] = args.due_at
    if args.snooze_until is not None:
        fields["snooze_until_utc"] = args.snooze_until
    if args.time_minutes is not None:
        fields["time_minutes"] = args.time_minutes
    if args.activation_energy is not None:
        fields["activation_energy"] = args.activation_energy
    if args.urgency is not None:
        fields["urgency"] = args.urgency
    if args.importance is not None:
        fields["importance"] = args.importance
    if args.project is not None:
        fields["project"] = args.project
    if args.blocked_reason is not None:
        fields["blocked_reason"] = args.blocked_reason
    if args.tags is not None:
        fields["tags"] = normalize_tags(args.tags.split(",")) if args.tags else []

    if not fields:
        return run_cli_action(action=lambda: fail_cli("no fields to update"))

    claim_token = getattr(args, "claim_token", None)
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_service.update_loop(
            loop_id=args.id,
            fields=fields,
            claim_token=claim_token,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=[
            *_claim_error_handlers(loop_id=args.id),
            error_handler(
                ValidationError,
                lambda exc: cli_error(str(exc)),
            ),
        ],
    )


def loop_status_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop status' command."""
    try:
        to_status = LoopStatus(args.status)
    except ValueError:
        return run_cli_action(action=lambda: fail_cli(f"invalid status '{args.status}'"))

    claim_token = getattr(args, "claim_token", None)

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_service.transition_status(
            loop_id=args.id,
            to_status=to_status,
            conn=conn,
            note=args.note,
            claim_token=claim_token,
        ),
        output_format=args.format,
        error_handlers=_transition_error_handlers(loop_id=args.id),
    )


def loop_close_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop close' command."""
    to_status = LoopStatus.DROPPED if args.dropped else LoopStatus.COMPLETED

    claim_token = getattr(args, "claim_token", None)

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_service.transition_status(
            loop_id=args.id,
            to_status=to_status,
            conn=conn,
            note=args.note,
            claim_token=claim_token,
        ),
        output_format=args.format,
        error_handlers=[
            *_claim_error_handlers(loop_id=args.id),
            error_handler(
                TransitionError,
                lambda exc: cli_error(str(exc), exit_code=2),
            ),
        ],
    )


def loop_enrich_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop enrich' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: orchestrate_loop_enrichment(
            loop_id=args.id,
            conn=conn,
            settings=settings,
        ).to_payload(),
        output_format=args.format,
        error_handlers=_loop_not_found_handler(loop_id=args.id),
    )


def parse_snooze_duration(duration: str) -> str | None:
    """Parse snooze duration. Supports: 30m, 1h, 2d, 1w, or ISO8601 timestamp."""
    try:
        return validate_iso8601_timestamp(duration, "snooze_until")
    except ValidationError:
        pass

    match = re.match(r"^(\d+)([mhdw])$", duration.strip())
    if not match:
        return None

    value, unit = int(match.group(1)), match.group(2)
    delta_map = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    delta = timedelta(**{delta_map[unit]: value})
    snooze_time = utc_now() + delta
    return format_utc_datetime(snooze_time)


def loop_snooze_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop snooze' command."""
    snooze_until = parse_snooze_duration(args.duration)
    if snooze_until is None:
        return run_cli_action(action=lambda: fail_cli(f"invalid duration '{args.duration}'"))

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: loop_service.update_loop(
            loop_id=args.id,
            fields={"snooze_until_utc": snooze_until},
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_loop_not_found_handler(loop_id=args.id),
    )
