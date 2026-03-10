"""Loop core command handlers.

Purpose:
    Implement CLI command handlers for core loop operations.

Responsibilities:
    - Handle capture, inbox, next, get, list, search, update, status, close, enrich, snooze commands

Non-scope:
    - Does not handle dependency operations (see loop_dep_commands.py)
    - Does not handle timer operations (see loop_timer_commands.py)
    - Does not handle view operations (see loop_view_commands.py)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from argparse import Namespace
from datetime import datetime, timedelta
from typing import Any, Dict

from .. import db
from ..loops import service
from ..loops.capture_orchestration import (
    CaptureFieldInputs,
    CaptureOrchestrationInput,
    CaptureStatusFlags,
    CaptureTemplateRef,
    orchestrate_capture,
)
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
from ..loops.service import (
    get_loop,
    list_loops,
    list_loops_by_statuses,
    list_loops_by_tag,
    next_loops,
    request_enrichment,
    transition_status,
    update_loop,
)
from ..loops.utils import normalize_tags
from ..settings import Settings
from .output import emit_output

logger = logging.getLogger(__name__)

_OPEN_STATUSES = [
    LoopStatus.INBOX,
    LoopStatus.ACTIONABLE,
    LoopStatus.BLOCKED,
    LoopStatus.SCHEDULED,
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

    try:
        with db.core_connection(settings) as conn:
            record = orchestrate_capture(
                input_data=input_data,
                settings=settings,
                conn=conn,
            ).loop
    except ValidationError as exc:
        logger.error("Capture validation failed: %s", exc)
        print(f"error: {exc.message}", file=sys.stderr)
        if exc.field in {"template_id", "template_name"}:
            return 2
        return 1

    print(json.dumps(record, indent=2))
    return 0


def inbox_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop inbox' command."""
    with db.core_connection(settings) as conn:
        records = list_loops(
            status=LoopStatus.INBOX,
            limit=args.limit,
            offset=0,
            conn=conn,
        )
    print(json.dumps(records, indent=2))
    return 0


def next_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop next' command."""
    with db.core_connection(settings) as conn:
        payload = next_loops(limit=args.limit, conn=conn)
    print(json.dumps(payload, indent=2))
    return 0


def loop_get_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop get' command."""
    try:
        with db.core_connection(settings) as conn:
            record = get_loop(loop_id=args.id, conn=conn)
        emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        logger.error("Loop %s not found", args.id)
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


def loop_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop list' command."""
    try:
        statuses = parse_list_status_filter(args.status)
    except ValueError as error:
        logger.error("Invalid status filter: %s", error)
        print(f"error: {error}", file=sys.stderr)
        return 1

    with db.core_connection(settings) as conn:
        if args.tag:
            records = list_loops_by_tag(
                tag=args.tag,
                statuses=statuses,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        elif statuses is None:
            records = list_loops(
                status=None,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        elif len(statuses) == 1:
            records = list_loops(
                status=statuses[0],
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        else:
            records = list_loops_by_statuses(
                statuses=statuses,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
    emit_output(records, args.format)
    return 0


def loop_search_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop search' command."""
    positional_query = args.query
    flag_query = args.query_flag
    if positional_query and flag_query:
        logger.error("Both positional and flag query provided")
        print("error: provide either positional query or --query, not both", file=sys.stderr)
        return 1
    query = flag_query or positional_query
    if not query:
        logger.error("No query provided")
        print("error: missing query (use positional value or --query)", file=sys.stderr)
        return 1

    try:
        with db.core_connection(settings) as conn:
            records = service.search_loops_by_query(
                query=query,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        emit_output(records, args.format)
        return 0
    except ValidationError as e:
        logger.error("Validation error in search: %s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except sqlite3.Error as e:
        logger.error("Database error in search: %s", e)
        print(f"error: database error - {e}", file=sys.stderr)
        return 1


def loop_update_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop update' command."""
    fields: Dict[str, Any] = {}
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
        logger.error("No fields to update")
        print("error: no fields to update", file=sys.stderr)
        return 1

    claim_token = getattr(args, "claim_token", None)

    try:
        with db.core_connection(settings) as conn:
            record = update_loop(loop_id=args.id, fields=fields, claim_token=claim_token, conn=conn)
        emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        logger.error("Loop %s not found", args.id)
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except LoopClaimedError as e:
        logger.error("Loop claimed: %s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ClaimNotFoundError:
        logger.error("Invalid or expired claim token")
        print("error: invalid or expired claim token", file=sys.stderr)
        return 1
    except ValidationError as e:
        logger.error("Validation error: %s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_status_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop status' command."""
    try:
        to_status = LoopStatus(args.status)
    except ValueError:
        logger.error("Invalid status: %s", args.status)
        print(f"error: invalid status '{args.status}'", file=sys.stderr)
        return 1

    claim_token = getattr(args, "claim_token", None)

    try:
        with db.core_connection(settings) as conn:
            record = transition_status(
                loop_id=args.id,
                to_status=to_status,
                conn=conn,
                note=args.note,
                claim_token=claim_token,
            )
        emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        logger.error("Loop %s not found", args.id)
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except LoopClaimedError as e:
        logger.error("Loop claimed: %s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ClaimNotFoundError:
        logger.error("Invalid or expired claim token")
        print("error: invalid or expired claim token", file=sys.stderr)
        return 1
    except TransitionError as e:
        logger.error("Invalid transition: %s -> %s", e.from_status, e.to_status)
        print(f"error: {e}", file=sys.stderr)
        return 2
    except DependencyNotMetError as e:
        logger.error("Dependencies not met for loop %s: %s", args.id, e.open_dependencies)
        print(f"error: {e.message} (open dependencies: {e.open_dependencies})", file=sys.stderr)
        return 2
    except DependencyCycleError as e:
        logger.error("Dependency cycle: %s", e)
        print(f"error: {e.message}", file=sys.stderr)
        return 2


def loop_close_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop close' command."""
    to_status = LoopStatus.DROPPED if args.dropped else LoopStatus.COMPLETED

    claim_token = getattr(args, "claim_token", None)

    try:
        with db.core_connection(settings) as conn:
            record = transition_status(
                loop_id=args.id,
                to_status=to_status,
                conn=conn,
                note=args.note,
                claim_token=claim_token,
            )
        emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        logger.error("Loop %s not found", args.id)
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except LoopClaimedError as e:
        logger.error("Loop claimed: %s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ClaimNotFoundError:
        logger.error("Invalid or expired claim token")
        print("error: invalid or expired claim token", file=sys.stderr)
        return 1
    except TransitionError as e:
        logger.error("Invalid transition: %s", e)
        print(f"error: {e}", file=sys.stderr)
        return 2


def loop_enrich_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop enrich' command."""
    try:
        with db.core_connection(settings) as conn:
            record = request_enrichment(loop_id=args.id, conn=conn)
        emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        logger.error("Loop %s not found", args.id)
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


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
        logger.error("Invalid duration: %s", args.duration)
        print(f"error: invalid duration '{args.duration}'", file=sys.stderr)
        return 1

    try:
        with db.core_connection(settings) as conn:
            record = update_loop(
                loop_id=args.id,
                fields={"snooze_until_utc": snooze_until},
                conn=conn,
            )
        emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        logger.error("Loop %s not found", args.id)
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
