"""Command-line interface for Cloop loop and retrieval workflows.

Purpose:
- Provide a local-first CLI for ingestion, retrieval, and full loop lifecycle management.

Responsibilities:
- Parse CLI arguments and route to service-layer functions.
- Normalize output for automation (`json`) and human review (`table`).
- Convert domain errors into stable process exit codes.

Non-scope:
- Business-rule validation and persistence logic (owned by service/repo layers).
- HTTP transport concerns (owned by FastAPI routes).

Invariants/assumptions:
- Exit code `0` means success.
- Exit code `1` means validation/input errors.
- Exit code `2` means missing resources or invalid state transitions.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from . import db
from .constants import DEFAULT_LOOP_LIST_LIMIT, DEFAULT_LOOP_NEXT_LIMIT
from .loops import repo
from .loops.errors import (
    ClaimNotFoundError,
    DependencyCycleError,
    DependencyNotMetError,
    LoopClaimedError,
    LoopNotFoundError,
    TransitionError,
    ValidationError,
)
from .loops.models import (
    LoopStatus,
    format_utc_datetime,
    resolve_status_from_flags,
    utc_now,
    validate_iso8601_timestamp,
)
from .loops.service import (
    add_loop_dependency,
    apply_loop_view,
    capture_loop,
    claim_loop,
    create_loop_view,
    delete_loop_view,
    export_loops,
    force_release_claim,
    get_claim_status,
    get_loop,
    get_loop_blocking,
    get_loop_dependencies,
    get_loop_view,
    get_timer_status,
    import_loops,
    list_active_claims,
    list_loop_views,
    list_loops,
    list_loops_by_statuses,
    list_loops_by_tag,
    list_tags,
    list_time_sessions,
    next_loops,
    release_claim,
    remove_loop_dependency,
    renew_claim,
    request_enrichment,
    search_loops_by_query,
    start_timer,
    stop_timer,
    transition_status,
    update_loop,
    update_loop_view,
)
from .rag import ingest_paths, retrieve_similar_chunks
from .settings import Settings, get_settings

_TABLE_EMPTY = "(no rows)"
_OPEN_STATUSES = [
    LoopStatus.INBOX,
    LoopStatus.ACTIONABLE,
    LoopStatus.BLOCKED,
    LoopStatus.SCHEDULED,
]
_LOOP_STATUS_VALUES = ", ".join(
    ["open", "all", "inbox", "actionable", "blocked", "scheduled", "completed", "dropped"]
)


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def _render_table(*, headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return _TABLE_EMPTY
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    header_line = " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    separator_line = "-+-".join("-" * width for width in widths)
    body_lines = [
        " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rows
    ]
    return "\n".join([header_line, separator_line, *body_lines])


def _emit_output(payload: Any, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return

    if isinstance(payload, list):
        if not payload:
            print(_TABLE_EMPTY)
            return
        if all(isinstance(item, dict) for item in payload):
            headers: list[str] = []
            for item in payload:
                item_map = dict(item)
                for key in item_map:
                    key_name = str(key)
                    if key_name not in headers:
                        headers.append(key_name)
            rows = [
                [_stringify_cell(dict(item).get(header)) for header in headers] for item in payload
            ]
            print(_render_table(headers=headers, rows=rows))
            return
        print(_render_table(headers=["value"], rows=[[_stringify_cell(item)] for item in payload]))
        return

    if isinstance(payload, dict):
        rows = [[str(key), _stringify_cell(value)] for key, value in payload.items()]
        print(_render_table(headers=["field", "value"], rows=rows))
        return

    print(_render_table(headers=["value"], rows=[[_stringify_cell(payload)]]))


def _parse_list_status_filter(raw_status: str | None) -> list[LoopStatus] | None:
    if raw_status is None or raw_status == "all":
        return None
    if raw_status == "open":
        return _OPEN_STATUSES
    try:
        return [LoopStatus(raw_status)]
    except ValueError:
        raise ValueError(
            f"invalid status '{raw_status}' (expected one of: {_LOOP_STATUS_VALUES})"
        ) from None


def _add_format_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="Output format (default: json)",
    )


def _ingest_command(args: argparse.Namespace, settings: Settings) -> int:
    result = ingest_paths(
        args.paths,
        mode=args.mode,
        recursive=not args.no_recursive,
        settings=settings,
    )
    print(json.dumps(result, indent=2))
    return 0


def _ask_command(args: argparse.Namespace, settings: Settings) -> int:
    chunks = retrieve_similar_chunks(
        args.question,
        top_k=args.k,
        scope=args.scope,
        settings=settings,
    )
    if not chunks:
        print("No knowledge available. Ingest documents first.", file=sys.stderr)
        return 1
    cleaned = [dict(chunk) for chunk in chunks]
    for chunk in cleaned:
        chunk.pop("embedding_blob", None)
    payload: Dict[str, Any] = {
        "question": args.question,
        "chunks": cleaned,
    }
    print(json.dumps(payload, indent=2))
    return 0


def _capture_command(args: argparse.Namespace, settings: Settings) -> int:
    local_now = datetime.now().astimezone()
    captured_at = args.captured_at or local_now.isoformat(timespec="seconds")
    tz_offset_min = args.tz_offset_min
    if tz_offset_min is None:
        offset = local_now.utcoffset()
        tz_offset_min = int(offset.total_seconds() / 60) if offset else 0

    status = resolve_status_from_flags(
        scheduled=args.scheduled,
        blocked=args.blocked,
        actionable=args.actionable,
    )

    # Resolve recurrence RRULE from schedule phrase or direct rrule
    recurrence_rrule: str | None = None
    if getattr(args, "schedule", None):
        from .loops.recurrence import parse_recurrence_schedule

        try:
            parsed = parse_recurrence_schedule(args.schedule)
            recurrence_rrule = parsed.rrule
        except Exception as e:
            print(f"error: invalid schedule: {e}", file=sys.stderr)
            return 1
    elif getattr(args, "rrule", None):
        recurrence_rrule = args.rrule

    # If template specified, fetch and apply
    template_defaults: dict[str, Any] = {}
    raw_text = args.text
    if getattr(args, "template", None):
        from .loops.repo import get_loop_template, get_loop_template_by_name
        from .loops.templates import (
            apply_template_to_capture,
            extract_update_fields_from_template,
        )

        with db.core_connection(settings) as conn:
            try:
                template_id = int(args.template)
                template = get_loop_template(template_id=template_id, conn=conn)
            except ValueError:
                template = get_loop_template_by_name(name=args.template, conn=conn)

        if not template:
            print(f"Template not found: {args.template}", file=sys.stderr)
            return 2

        applied = apply_template_to_capture(
            template=template,
            raw_text_override=args.text,
            now_utc=utc_now(),
            tz_offset_min=tz_offset_min,
        )
        raw_text = applied["raw_text"]
        template_defaults = applied

        # Merge status flags from template if not explicitly set
        if not args.actionable and not args.scheduled and not args.blocked:
            status = resolve_status_from_flags(
                scheduled=applied.get("scheduled", False),
                blocked=applied.get("blocked", False),
                actionable=applied.get("actionable", False),
            )

    with db.core_connection(settings) as conn:
        record = capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=tz_offset_min,
            status=status,
            conn=conn,
            recurrence_rrule=recurrence_rrule,
            recurrence_tz=getattr(args, "timezone", None),
        )

        # Apply template defaults (tags, time_minutes, etc.)
        if template_defaults:
            update_fields = extract_update_fields_from_template(template_defaults)
            if update_fields:
                record = update_loop(
                    loop_id=record["id"],
                    fields=update_fields,
                    conn=conn,
                )

        if settings.autopilot_enabled:
            record = request_enrichment(loop_id=record["id"], conn=conn)

    print(json.dumps(record, indent=2))
    return 0


def _inbox_command(args: argparse.Namespace, settings: Settings) -> int:
    with db.core_connection(settings) as conn:
        records = list_loops(
            status=LoopStatus.INBOX,
            limit=args.limit,
            offset=0,
            conn=conn,
        )
    print(json.dumps(records, indent=2))
    return 0


def _next_command(args: argparse.Namespace, settings: Settings) -> int:
    with db.core_connection(settings) as conn:
        payload = next_loops(limit=args.limit, conn=conn)
    print(json.dumps(payload, indent=2))
    return 0


def _review_command(args: argparse.Namespace, settings: Settings) -> int:
    """Handle 'cloop loop review' command."""
    from .loops.models import utc_now
    from .loops.review import compute_review_cohorts

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

    _emit_output(output, args.format)
    return 0


def _loop_get_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            record = get_loop(loop_id=args.id, conn=conn)
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


def _loop_list_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        statuses = _parse_list_status_filter(args.status)
    except ValueError as error:
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
    _emit_output(records, args.format)
    return 0


def _loop_search_command(args: argparse.Namespace, settings: Settings) -> int:
    positional_query = args.query
    flag_query = args.query_flag
    if positional_query and flag_query:
        print("error: provide either positional query or --query, not both", file=sys.stderr)
        return 1
    query = flag_query or positional_query
    if not query:
        print("error: missing query (use positional value or --query)", file=sys.stderr)
        return 1

    try:
        with db.core_connection(settings) as conn:
            records = search_loops_by_query(
                query=query,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        _emit_output(records, args.format)
        return 0
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_update_command(args: argparse.Namespace, settings: Settings) -> int:
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
        fields["tags"] = [t.strip().lower() for t in args.tags.split(",")] if args.tags else []

    if not fields:
        print("error: no fields to update", file=sys.stderr)
        return 1

    claim_token = getattr(args, "claim_token", None)

    try:
        with db.core_connection(settings) as conn:
            record = update_loop(loop_id=args.id, fields=fields, claim_token=claim_token, conn=conn)
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except LoopClaimedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ClaimNotFoundError:
        print("error: invalid or expired claim token", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_status_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        to_status = LoopStatus(args.status)
    except ValueError:
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
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except LoopClaimedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ClaimNotFoundError:
        print("error: invalid or expired claim token", file=sys.stderr)
        return 1
    except TransitionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except DependencyNotMetError as e:
        print(f"error: {e.message} (open dependencies: {e.open_dependencies})", file=sys.stderr)
        return 2
    except DependencyCycleError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 2


def _loop_close_command(args: argparse.Namespace, settings: Settings) -> int:
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
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except LoopClaimedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ClaimNotFoundError:
        print("error: invalid or expired claim token", file=sys.stderr)
        return 1
    except TransitionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _loop_enrich_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            record = request_enrichment(loop_id=args.id, conn=conn)
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


def _parse_snooze_duration(duration: str) -> str | None:
    """Parse snooze duration. Supports: 30m, 1h, 2d, 1w, or ISO8601 timestamp."""
    try:
        return validate_iso8601_timestamp(duration, "snooze_until")
    except Exception:
        pass

    match = re.match(r"^(\d+)([mhdw])$", duration.strip())
    if not match:
        return None

    value, unit = int(match.group(1)), match.group(2)
    delta_map = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    delta = timedelta(**{delta_map[unit]: value})
    snooze_time = utc_now() + delta
    return format_utc_datetime(snooze_time)


def _loop_snooze_command(args: argparse.Namespace, settings: Settings) -> int:
    snooze_until = _parse_snooze_duration(args.duration)
    if snooze_until is None:
        print(f"error: invalid duration '{args.duration}'", file=sys.stderr)
        return 1

    try:
        with db.core_connection(settings) as conn:
            record = update_loop(
                loop_id=args.id,
                fields={"snooze_until_utc": snooze_until},
                conn=conn,
            )
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


def _tags_command(args: argparse.Namespace, settings: Settings) -> int:
    with db.core_connection(settings) as conn:
        tags = list_tags(conn=conn)
    _emit_output(tags, args.format)
    return 0


def _projects_command(args: argparse.Namespace, settings: Settings) -> int:
    with db.core_connection(settings) as conn:
        projects = repo.list_projects(conn=conn)
    _emit_output(projects, args.format)
    return 0


def _export_command(args: argparse.Namespace, settings: Settings) -> int:
    with db.core_connection(settings) as conn:
        loops = export_loops(conn=conn)
    payload = {"version": 1, "loops": loops}
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2))
        print(f"Exported {len(loops)} loops to {args.output}", file=sys.stderr)
    else:
        _emit_output(payload, args.format)
    return 0


def _import_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.file:
            data = json.loads(Path(args.file).read_text())
        else:
            data = json.loads(sys.stdin.read())

        loops = data.get("loops", data) if isinstance(data, dict) else data

        with db.core_connection(settings) as conn:
            imported = import_loops(loops=loops, conn=conn)

        _emit_output({"imported": imported}, args.format)
        return 0
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_view_create_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            view = create_loop_view(
                name=args.name,
                query=args.query,
                description=args.description,
                conn=conn,
            )
        _emit_output(view, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_view_list_command(args: argparse.Namespace, settings: Settings) -> int:
    with db.core_connection(settings) as conn:
        views = list_loop_views(conn=conn)
    _emit_output(views, args.format)
    return 0


def _loop_view_get_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            view = get_loop_view(view_id=args.id, conn=conn)
        _emit_output(view, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_view_update_command(args: argparse.Namespace, settings: Settings) -> int:
    fields: Dict[str, Any] = {}
    if args.name is not None:
        fields["name"] = args.name
    if args.query is not None:
        fields["query"] = args.query
    if args.description is not None:
        fields["description"] = args.description

    if not fields:
        print("error: no fields to update", file=sys.stderr)
        return 1

    try:
        with db.core_connection(settings) as conn:
            view = update_loop_view(view_id=args.id, conn=conn, **fields)
        _emit_output(view, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_view_delete_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            delete_loop_view(view_id=args.id, conn=conn)
        _emit_output({"deleted": True}, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_view_apply_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            result = apply_loop_view(
                view_id=args.id,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        _emit_output(result, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


# ============================================================================
# Loop Claim Commands
# ============================================================================


def _loop_claim_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            result = claim_loop(
                loop_id=args.id,
                owner=args.owner,
                ttl_seconds=args.ttl,
                conn=conn,
                settings=settings,
            )
        _emit_output(result, args.format)
        return 0
    except LoopClaimedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


def _loop_renew_claim_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            result = renew_claim(
                loop_id=args.id,
                claim_token=args.token,
                ttl_seconds=args.ttl,
                conn=conn,
                settings=settings,
            )
        _emit_output(result, args.format)
        return 0
    except ClaimNotFoundError:
        print(f"error: no valid claim found for loop {args.id}", file=sys.stderr)
        return 1


def _loop_release_claim_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            release_claim(
                loop_id=args.id,
                claim_token=args.token,
                conn=conn,
            )
        _emit_output({"ok": True, "loop_id": args.id}, args.format)
        return 0
    except ClaimNotFoundError:
        print(f"error: no valid claim found for loop {args.id}", file=sys.stderr)
        return 1


def _loop_get_claim_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            result = get_claim_status(loop_id=args.id, conn=conn)
        if result is None:
            print(f"Loop {args.id} is not claimed", file=sys.stderr)
            return 0
        _emit_output(result, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_list_claims_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            result = list_active_claims(
                owner=args.owner,
                limit=args.limit,
                conn=conn,
            )
        _emit_output(result, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_force_release_claim_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        with db.core_connection(settings) as conn:
            released = force_release_claim(loop_id=args.id, conn=conn)
        _emit_output({"ok": True, "released": released, "loop_id": args.id}, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_dep_command(args: argparse.Namespace, settings: Settings) -> int:
    action = args.dep_action
    try:
        with db.core_connection(settings) as conn:
            if action == "add":
                if not args.loop_id or not args.depends_on:
                    print("error: --loop and --on required for add", file=sys.stderr)
                    return 2
                try:
                    result = add_loop_dependency(
                        loop_id=args.loop_id,
                        depends_on_loop_id=args.depends_on,
                        conn=conn,
                    )
                    _emit_output(result, args.format)
                    return 0
                except DependencyCycleError as e:
                    print(f"error: {e.message}", file=sys.stderr)
                    return 1

            elif action == "remove":
                if not args.loop_id or not args.depends_on:
                    print("error: --loop and --on required for remove", file=sys.stderr)
                    return 2
                result = remove_loop_dependency(
                    loop_id=args.loop_id,
                    depends_on_loop_id=args.depends_on,
                    conn=conn,
                )
                _emit_output(result, args.format)
                return 0

            elif action == "list":
                if not args.loop_id:
                    print("error: --loop required for list", file=sys.stderr)
                    return 2
                deps = get_loop_dependencies(loop_id=args.loop_id, conn=conn)
                _emit_output(deps, args.format)
                return 0

            elif action == "blocking":
                if not args.loop_id:
                    print("error: --loop required for blocking", file=sys.stderr)
                    return 2
                blocking = get_loop_blocking(loop_id=args.loop_id, conn=conn)
                _emit_output(blocking, args.format)
                return 0

            else:
                print(f"error: unknown dep action: {action}", file=sys.stderr)
                return 2
    except LoopNotFoundError as e:
        print(f"error: loop not found: {e.loop_id}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _timer_command(args: argparse.Namespace, settings: Settings) -> int:
    """Handle timer start/stop/status commands."""
    from .loops.service import ActiveTimerExistsError, NoActiveTimerError

    action = args.timer_action
    loop_id = args.id

    try:
        with db.core_connection(settings) as conn:
            if action == "start":
                try:
                    session = start_timer(loop_id=loop_id, conn=conn)
                    print(f"Timer started for loop {loop_id}")
                    print(f"  Session ID: {session.id}")
                    print(f"  Started at: {format_utc_datetime(session.started_at_utc)}")
                    return 0
                except ActiveTimerExistsError as e:
                    print(f"Error: Timer already running for loop {loop_id}", file=sys.stderr)
                    print(f"  Session ID: {e.session.id}", file=sys.stderr)
                    print(
                        f"  Started at: {format_utc_datetime(e.session.started_at_utc)}",
                        file=sys.stderr,
                    )
                    return 1
                except LoopNotFoundError:
                    print(f"Error: Loop {loop_id} not found", file=sys.stderr)
                    return 2

            elif action == "stop":
                try:
                    notes = getattr(args, "notes", None)
                    session = stop_timer(loop_id=loop_id, notes=notes, conn=conn)
                    print(f"Timer stopped for loop {loop_id}")
                    print(f"  Session ID: {session.id}")
                    duration = session.duration_seconds or 0
                    duration_mins = duration // 60
                    print(f"  Duration: {duration}s ({duration_mins}m)")
                    if session.notes:
                        print(f"  Notes: {session.notes}")
                    return 0
                except NoActiveTimerError:
                    print(f"Error: No active timer for loop {loop_id}", file=sys.stderr)
                    return 1
                except LoopNotFoundError:
                    print(f"Error: Loop {loop_id} not found", file=sys.stderr)
                    return 2

            elif action == "status":
                try:
                    status = get_timer_status(loop_id=loop_id, conn=conn)
                    print(f"Timer status for loop {loop_id}:")
                    if status.has_active_session and status.active_session:
                        elapsed = status.active_session.elapsed_seconds
                        print("  Status: RUNNING")
                        print(f"  Session ID: {status.active_session.id}")
                        started = format_utc_datetime(status.active_session.started_at_utc)
                        print(f"  Started: {started}")
                        print(f"  Elapsed: {elapsed}s ({elapsed // 60}m {elapsed % 60}s)")
                    else:
                        print("  Status: STOPPED")

                    total_min = status.total_tracked_seconds // 60
                    total_sec = status.total_tracked_seconds % 60
                    print(f"  Total tracked: {total_min}m {total_sec}s")

                    if status.estimated_minutes:
                        print(f"  Estimated: {status.estimated_minutes}m")
                        if total_min > 0:
                            ratio = round(total_min / status.estimated_minutes, 2)
                            print(f"  Actual/Estimate: {ratio}x")
                    return 0
                except LoopNotFoundError:
                    print(f"Error: Loop {loop_id} not found", file=sys.stderr)
                    return 2

            else:
                print(f"Error: Unknown timer action: {action}", file=sys.stderr)
                return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _sessions_command(args: argparse.Namespace, settings: Settings) -> int:
    """List time sessions for a loop."""
    loop_id = args.id
    limit = getattr(args, "limit", 20)

    try:
        with db.core_connection(settings) as conn:
            sessions = list_time_sessions(
                loop_id=loop_id,
                limit=limit,
                offset=0,
                conn=conn,
            )

            if not sessions:
                print(f"No time sessions for loop {loop_id}")
                return 0

            print(f"Time sessions for loop {loop_id}:")
            print("-" * 60)

            for s in sessions:
                status = "ACTIVE" if s.is_active else f"{s.duration_seconds}s"
                duration = f"{s.duration_seconds // 60}m" if s.duration_seconds else "running"
                started = format_utc_datetime(s.started_at_utc)
                print(f"  [{s.id}] {started} - {duration} ({status})")
                if s.notes:
                    print(f"       Notes: {s.notes}")

            return 0
    except LoopNotFoundError:
        print(f"Error: Loop {loop_id} not found", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _template_list_command(args: argparse.Namespace, settings: Settings) -> int:
    from .loops.repo import list_loop_templates

    with db.core_connection(settings) as conn:
        templates = list_loop_templates(conn=conn)

    payload = [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "is_system": bool(t["is_system"]),
        }
        for t in templates
    ]
    _emit_output(payload, args.format)
    return 0


def _template_show_command(args: argparse.Namespace, settings: Settings) -> int:
    import json

    from .loops.repo import get_loop_template, get_loop_template_by_name

    with db.core_connection(settings) as conn:
        # Try as ID first
        try:
            template_id = int(args.name_or_id)
            template = get_loop_template(template_id=template_id, conn=conn)
        except ValueError:
            template = get_loop_template_by_name(name=args.name_or_id, conn=conn)

    if not template:
        print(f"Template not found: {args.name_or_id}", file=sys.stderr)
        return 2

    defaults = json.loads(template["defaults_json"]) if template["defaults_json"] else {}
    payload = {
        "id": template["id"],
        "name": template["name"],
        "description": template["description"],
        "pattern": template["raw_text_pattern"],
        "defaults": defaults,
        "is_system": bool(template["is_system"]),
    }
    _emit_output(payload, args.format)
    return 0


def _template_create_command(args: argparse.Namespace, settings: Settings) -> int:

    from .loops.errors import ValidationError
    from .loops.repo import create_loop_template

    defaults: dict[str, Any] = {}
    if args.tags:
        defaults["tags"] = [t.strip().lower() for t in args.tags.split(",")]
    if args.time:
        defaults["time_minutes"] = args.time
    if args.actionable:
        defaults["actionable"] = True

    with db.core_connection(settings) as conn:
        try:
            template = create_loop_template(
                name=args.name,
                description=args.description,
                raw_text_pattern=args.pattern,
                defaults_json=defaults,
                is_system=False,
                conn=conn,
            )
        except ValidationError as e:
            print(f"Error: {e.message}", file=sys.stderr)
            return 1

    _emit_output({"id": template["id"], "name": template["name"]}, args.format)
    return 0


def _template_delete_command(args: argparse.Namespace, settings: Settings) -> int:
    from .loops.errors import ValidationError
    from .loops.repo import delete_loop_template, get_loop_template, get_loop_template_by_name

    with db.core_connection(settings) as conn:
        try:
            template_id = int(args.name_or_id)
            template = get_loop_template(template_id=template_id, conn=conn)
        except ValueError:
            template = get_loop_template_by_name(name=args.name_or_id, conn=conn)

        if not template:
            print(f"Template not found: {args.name_or_id}", file=sys.stderr)
            return 2

        try:
            deleted = delete_loop_template(template_id=template["id"], conn=conn)
        except ValidationError as e:
            print(f"Cannot delete: {e.message}", file=sys.stderr)
            return 1

    if deleted:
        print(f"Deleted template: {template['name']}")
        return 0
    return 1


def _template_from_loop_command(args: argparse.Namespace, settings: Settings) -> int:
    from .loops.errors import LoopNotFoundError, ValidationError
    from .loops.service import create_template_from_loop

    with db.core_connection(settings) as conn:
        try:
            template = create_template_from_loop(
                loop_id=args.loop_id,
                template_name=args.name,
                conn=conn,
            )
        except LoopNotFoundError:
            print(f"Loop not found: {args.loop_id}", file=sys.stderr)
            return 2
        except ValidationError as e:
            print(f"Error: {e.message}", file=sys.stderr)
            return 1

    _emit_output({"id": template["id"], "name": template["name"]}, args.format)
    return 0


def _backup_create_command(args: argparse.Namespace, settings: Settings) -> int:
    """Handle 'cloop backup create' command."""
    from .backup import create_backup

    result = create_backup(
        settings=settings,
        output_dir=args.output,
        name=args.name,
    )

    if result.success:
        output = {
            "success": True,
            "backup_path": str(result.backup_path),
            "manifest": result.manifest.__dict__ if result.manifest else None,
        }
        print(json.dumps(output, indent=2))
        return 0
    else:
        print(json.dumps({"success": False, "error": result.error}), file=sys.stderr)
        return 1


def _backup_restore_command(args: argparse.Namespace, settings: Settings) -> int:
    """Handle 'cloop backup restore' command."""
    from .backup import restore_backup

    result = restore_backup(
        settings=settings,
        backup_path=args.backup_path,
        dry_run=args.dry_run,
        force=args.force,
    )

    if result.success:
        output = {
            "success": True,
            "dry_run": result.dry_run,
            "backup_path": str(result.backup_path),
            "manifest": result.manifest.__dict__ if result.manifest else None,
            "core_restored": result.core_restored,
            "rag_restored": result.rag_restored,
        }
        print(json.dumps(output, indent=2))
        return 0
    else:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": result.error,
                    "manifest": result.manifest.__dict__ if result.manifest else None,
                }
            ),
            file=sys.stderr,
        )
        return 1


def _backup_list_command(args: argparse.Namespace, settings: Settings) -> int:
    """Handle 'cloop backup list' command."""
    from .backup import list_backups

    backups = list_backups(settings=settings, limit=args.limit)

    output = [
        {
            "path": str(b.path),
            "created_at_utc": b.created_at_utc,
            "name": b.name,
            "core_schema_version": b.core_schema_version,
            "rag_schema_version": b.rag_schema_version,
            "size_bytes": b.size_bytes,
        }
        for b in backups
    ]
    print(json.dumps(output, indent=2))
    return 0


def _backup_verify_command(args: argparse.Namespace, settings: Settings) -> int:
    """Handle 'cloop backup verify' command."""
    from .backup import verify_backup

    result = verify_backup(backup_path=args.backup_path)

    output = {
        "valid": result.valid,
        "backup_path": str(result.backup_path),
        "manifest": result.manifest.__dict__ if result.manifest else None,
        "core_integrity": result.core_integrity,
        "rag_integrity": result.rag_integrity,
        "errors": result.errors,
    }
    print(json.dumps(output, indent=2))
    return 0 if result.valid else 1


def _backup_rotate_command(args: argparse.Namespace, settings: Settings) -> int:
    """Handle 'cloop backup rotate' command."""
    from .backup import list_backups, rotate_backups

    if args.dry_run:
        backups = list_backups(settings=settings)
        to_delete = backups[settings.backup_keep_count :]
        output = {
            "dry_run": True,
            "keep_count": settings.backup_keep_count,
            "total_backups": len(backups),
            "would_delete": [str(b.path) for b in to_delete],
        }
        print(json.dumps(output, indent=2))
        return 0

    deleted = rotate_backups(settings=settings)
    output = {
        "deleted": [str(d) for d in deleted],
        "count": len(deleted),
    }
    print(json.dumps(output, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
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
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_ingest_parser(subparsers)
    _add_ask_parser(subparsers)
    _add_capture_parser(subparsers)
    _add_inbox_parser(subparsers)
    _add_next_parser(subparsers)

    _add_loop_parser(subparsers)
    _add_template_parser(subparsers)

    _add_tags_parser(subparsers)
    _add_projects_parser(subparsers)
    _add_export_parser(subparsers)
    _add_import_parser(subparsers)
    _add_backup_parser(subparsers)

    return parser


def _add_ingest_parser(subparsers: Any) -> None:
    ingest_parser = subparsers.add_parser("ingest", help="Ingest documents")
    ingest_parser.add_argument("paths", nargs="+", help="Files or directories to ingest")
    ingest_parser.add_argument(
        "--mode",
        choices=["add", "reindex", "purge", "sync"],
        default="add",
        help="Ingestion mode",
    )
    ingest_parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Disable directory recursion",
    )


def _add_ask_parser(subparsers: Any) -> None:
    ask_parser = subparsers.add_parser("ask", help="Query the knowledge base")
    ask_parser.add_argument("question", help="Question text")
    ask_parser.add_argument("--k", type=int, default=5, help="Top-k chunks to retrieve")
    ask_parser.add_argument(
        "--scope",
        help="Restrict retrieval by path substring or doc:<id>",
    )


def _add_capture_parser(subparsers: Any) -> None:
    capture_parser = subparsers.add_parser("capture", help="Capture a loop")
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


def _add_inbox_parser(subparsers: Any) -> None:
    inbox_parser = subparsers.add_parser("inbox", help="List inbox loops")
    inbox_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LOOP_LIST_LIMIT, help="Max loops to return"
    )


def _add_next_parser(subparsers: Any) -> None:
    next_parser = subparsers.add_parser("next", help="Show the next loops")
    next_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LOOP_NEXT_LIMIT, help="Max loops per bucket"
    )


def _add_loop_parser(subparsers: Any) -> None:
    loop_parser = subparsers.add_parser("loop", help="Loop lifecycle commands")
    loop_subparsers = loop_parser.add_subparsers(dest="loop_command", required=True)

    get_parser = loop_subparsers.add_parser("get", help="Get a loop by ID")
    get_parser.add_argument("id", type=int, help="Loop ID")
    _add_format_option(get_parser)

    list_parser = loop_subparsers.add_parser("list", help="List loops")
    list_parser.add_argument(
        "--status",
        default="open",
        help=f"Filter by status ({_LOOP_STATUS_VALUES})",
    )
    list_parser.add_argument("--tag", help="Filter by tag")
    list_parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    list_parser.add_argument("--offset", type=int, default=0, help="Pagination offset (default: 0)")
    _add_format_option(list_parser)

    search_parser = loop_subparsers.add_parser("search", help="Search loops with DSL query")
    search_parser.add_argument("query", nargs="?", help="DSL query string")
    search_parser.add_argument("--query", dest="query_flag", help="DSL query string")
    search_parser.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")
    search_parser.add_argument(
        "--offset", type=int, default=0, help="Pagination offset (default: 0)"
    )
    _add_format_option(search_parser)

    update_parser = loop_subparsers.add_parser("update", help="Update loop fields")
    update_parser.add_argument("id", type=int, help="Loop ID")
    update_parser.add_argument("--title", help="Update title")
    update_parser.add_argument("--summary", help="Update summary")
    update_parser.add_argument("--next-action", dest="next_action", help="Update next action")
    update_parser.add_argument("--due-at", dest="due_at", help="Update due date (ISO8601)")
    update_parser.add_argument(
        "--snooze-until", dest="snooze_until", help="Update snooze time (ISO8601)"
    )
    update_parser.add_argument(
        "--time-minutes", dest="time_minutes", type=int, help="Estimated time"
    )
    update_parser.add_argument(
        "--activation-energy",
        dest="activation_energy",
        type=int,
        choices=[0, 1, 2, 3],
        help="Activation energy (0-3)",
    )
    update_parser.add_argument("--urgency", type=float, help="Urgency (0.0-1.0)")
    update_parser.add_argument("--importance", type=float, help="Importance (0.0-1.0)")
    update_parser.add_argument("--project", help="Project name")
    update_parser.add_argument(
        "--blocked-reason", dest="blocked_reason", help="Reason for blocked status"
    )
    update_parser.add_argument(
        "--tags",
        help="Comma-separated tags (clears existing tags, use empty string to clear all)",
    )
    update_parser.add_argument(
        "--claim-token", dest="claim_token", help="Claim token for claimed loops"
    )
    _add_format_option(update_parser)

    status_parser = loop_subparsers.add_parser("status", help="Transition loop status")
    status_parser.add_argument("id", type=int, help="Loop ID")
    status_parser.add_argument(
        "status",
        help="Target status (inbox, actionable, blocked, scheduled, completed, dropped)",
    )
    status_parser.add_argument(
        "--note",
        help="Optional note (used for completion_note when completing)",
    )
    status_parser.add_argument(
        "--claim-token", dest="claim_token", help="Claim token for claimed loops"
    )
    _add_format_option(status_parser)

    close_parser = loop_subparsers.add_parser("close", help="Close a loop")
    close_parser.add_argument("id", type=int, help="Loop ID")
    close_parser.add_argument(
        "--dropped",
        action="store_true",
        help="Close as dropped instead of completed",
    )
    close_parser.add_argument("--note", help="Completion/drop note")
    close_parser.add_argument(
        "--claim-token", dest="claim_token", help="Claim token for claimed loops"
    )
    _add_format_option(close_parser)

    enrich_parser = loop_subparsers.add_parser("enrich", help="Request AI enrichment")
    enrich_parser.add_argument("id", type=int, help="Loop ID")
    _add_format_option(enrich_parser)

    snooze_parser = loop_subparsers.add_parser("snooze", help="Snooze a loop")
    snooze_parser.add_argument("id", type=int, help="Loop ID")
    snooze_parser.add_argument(
        "duration",
        help="Duration (30m, 1h, 2d, 1w) or ISO8601 timestamp",
    )
    _add_format_option(snooze_parser)

    view_parser = loop_subparsers.add_parser("view", help="Saved view operations")
    view_subparsers = view_parser.add_subparsers(dest="view_command", required=True)

    view_create_parser = view_subparsers.add_parser("create", help="Create a saved view")
    view_create_parser.add_argument("--name", required=True, help="View name")
    view_create_parser.add_argument("--query", required=True, help="DSL query string")
    view_create_parser.add_argument("--description", help="Optional description")
    _add_format_option(view_create_parser)

    view_list_parser = view_subparsers.add_parser("list", help="List saved views")
    _add_format_option(view_list_parser)

    view_get_parser = view_subparsers.add_parser("get", help="Get a saved view")
    view_get_parser.add_argument("id", type=int, help="View ID")
    _add_format_option(view_get_parser)

    view_update_parser = view_subparsers.add_parser("update", help="Update a saved view")
    view_update_parser.add_argument("id", type=int, help="View ID")
    view_update_parser.add_argument("--name", help="New view name")
    view_update_parser.add_argument("--query", help="New DSL query string")
    view_update_parser.add_argument("--description", help="New description")
    _add_format_option(view_update_parser)

    view_delete_parser = view_subparsers.add_parser("delete", help="Delete a saved view")
    view_delete_parser.add_argument("id", type=int, help="View ID")
    _add_format_option(view_delete_parser)

    view_apply_parser = view_subparsers.add_parser("apply", help="Apply a saved view")
    view_apply_parser.add_argument("id", type=int, help="View ID")
    view_apply_parser.add_argument("--limit", type=int, default=50, help="Max results")
    view_apply_parser.add_argument("--offset", type=int, default=0, help="Pagination offset")
    _add_format_option(view_apply_parser)

    # Claim parsers
    claim_parser = loop_subparsers.add_parser("claim", help="Claim a loop for exclusive access")
    claim_parser.add_argument("id", type=int, help="Loop ID")
    claim_parser.add_argument(
        "--owner", "-o", default="cli-user", help="Owner identifier (default: cli-user)"
    )
    claim_parser.add_argument(
        "--ttl", "-t", type=int, default=300, help="Lease duration in seconds (default: 300)"
    )
    _add_format_option(claim_parser)

    renew_claim_parser = loop_subparsers.add_parser("renew", help="Renew an existing claim")
    renew_claim_parser.add_argument("id", type=int, help="Loop ID")
    renew_claim_parser.add_argument(
        "--token", "-t", required=True, help="Claim token from original claim"
    )
    renew_claim_parser.add_argument(
        "--ttl", type=int, default=300, help="New lease duration in seconds (default: 300)"
    )
    _add_format_option(renew_claim_parser)

    release_claim_parser = loop_subparsers.add_parser("release", help="Release a claim")
    release_claim_parser.add_argument("id", type=int, help="Loop ID")
    release_claim_parser.add_argument(
        "--token", "-t", required=True, help="Claim token from original claim"
    )
    _add_format_option(release_claim_parser)

    get_claim_parser = loop_subparsers.add_parser("get-claim", help="Get claim status for a loop")
    get_claim_parser.add_argument("id", type=int, help="Loop ID")
    _add_format_option(get_claim_parser)

    list_claims_parser = loop_subparsers.add_parser("claims", help="List active claims")
    list_claims_parser.add_argument("--owner", "-o", help="Filter by owner")
    list_claims_parser.add_argument("--limit", type=int, default=100, help="Max results")
    _add_format_option(list_claims_parser)

    force_release_parser = loop_subparsers.add_parser(
        "force-release", help="Force-release any claim (admin override)"
    )
    force_release_parser.add_argument("id", type=int, help="Loop ID")
    _add_format_option(force_release_parser)

    # Dependency parsers
    dep_parser = loop_subparsers.add_parser("dep", help="Manage loop dependencies")
    dep_subparsers = dep_parser.add_subparsers(dest="dep_action", required=True)

    dep_add_parser = dep_subparsers.add_parser("add", help="Add a dependency")
    dep_add_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    dep_add_parser.add_argument(
        "--on", "-o", type=int, dest="depends_on", required=True, help="Depends on loop ID"
    )
    _add_format_option(dep_add_parser)

    dep_remove_parser = dep_subparsers.add_parser("remove", help="Remove a dependency")
    dep_remove_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    dep_remove_parser.add_argument(
        "--on", "-o", type=int, dest="depends_on", required=True, help="Depends on loop ID"
    )
    _add_format_option(dep_remove_parser)

    dep_list_parser = dep_subparsers.add_parser("list", help="List dependencies")
    dep_list_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    _add_format_option(dep_list_parser)

    dep_blocking_parser = dep_subparsers.add_parser("blocking", help="List what this loop blocks")
    dep_blocking_parser.add_argument(
        "--loop", "-l", type=int, dest="loop_id", required=True, help="Loop ID"
    )
    _add_format_option(dep_blocking_parser)

    # Timer parsers
    timer_parser = loop_subparsers.add_parser("timer", help="Start/stop timer for a loop")
    timer_subparsers = timer_parser.add_subparsers(dest="timer_action", required=True)

    timer_start_parser = timer_subparsers.add_parser("start", help="Start timer")
    timer_start_parser.add_argument("id", type=int, help="Loop ID")

    timer_stop_parser = timer_subparsers.add_parser("stop", help="Stop timer")
    timer_stop_parser.add_argument("id", type=int, help="Loop ID")
    timer_stop_parser.add_argument("--notes", help="Optional notes for this session")

    timer_status_parser = timer_subparsers.add_parser("status", help="Get timer status")
    timer_status_parser.add_argument("id", type=int, help="Loop ID")

    # Sessions parser
    sessions_parser = loop_subparsers.add_parser("sessions", help="List time sessions for a loop")
    sessions_parser.add_argument("id", type=int, help="Loop ID")
    sessions_parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    # Review parser
    review_parser = loop_subparsers.add_parser(
        "review",
        help="Show review cohorts for maintenance",
        description="Display daily/weekly review cohorts for stale-loop cleanup",
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
    _add_format_option(review_parser)


def _add_tags_parser(subparsers: Any) -> None:
    tags_parser = subparsers.add_parser("tags", help="List all tags")
    _add_format_option(tags_parser)


def _add_projects_parser(subparsers: Any) -> None:
    projects_parser = subparsers.add_parser("projects", help="List all projects")
    _add_format_option(projects_parser)


def _add_export_parser(subparsers: Any) -> None:
    export_parser = subparsers.add_parser("export", help="Export loops")
    export_parser.add_argument("--output", help="Write to file instead of stdout")
    _add_format_option(export_parser)


def _add_import_parser(subparsers: Any) -> None:
    import_parser = subparsers.add_parser("import", help="Import loops")
    import_parser.add_argument("--file", help="Read from file instead of stdin")
    _add_format_option(import_parser)


def _add_backup_parser(subparsers: Any) -> None:
    backup_parser = subparsers.add_parser(
        "backup",
        help="Backup and restore commands",
        description="Manage Cloop data backups",
    )
    backup_subparsers = backup_parser.add_subparsers(dest="backup_command", required=True)

    # cloop backup create
    backup_create_parser = backup_subparsers.add_parser(
        "create",
        help="Create a new backup",
        description="Create a timestamped backup of all Cloop data",
    )
    backup_create_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output directory for backup (default: data_dir/backups)",
    )
    backup_create_parser.add_argument(
        "--name",
        "-n",
        type=str,
        default="manual",
        help="Backup name for identification (default: manual)",
    )

    # cloop backup restore
    backup_restore_parser = backup_subparsers.add_parser(
        "restore",
        help="Restore from a backup",
        description="Restore databases from a backup archive",
    )
    backup_restore_parser.add_argument(
        "backup_path",
        type=Path,
        help="Path to the .cloop.zip backup file",
    )
    backup_restore_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate backup without making changes",
    )
    backup_restore_parser.add_argument(
        "--force",
        action="store_true",
        help="Restore even if schema versions differ",
    )

    # cloop backup list
    backup_list_parser = backup_subparsers.add_parser(
        "list",
        help="List available backups",
        description="List backups in the backup directory",
    )
    backup_list_parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=20,
        help="Maximum number of backups to show (default: 20)",
    )

    # cloop backup verify
    backup_verify_parser = backup_subparsers.add_parser(
        "verify",
        help="Verify backup integrity",
        description="Validate backup archive without restoring",
    )
    backup_verify_parser.add_argument(
        "backup_path",
        type=Path,
        help="Path to the .cloop.zip backup file",
    )

    # cloop backup rotate
    backup_rotate_parser = backup_subparsers.add_parser(
        "rotate",
        help="Rotate old backups",
        description="Delete oldest backups exceeding backup_keep_count",
    )
    backup_rotate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )


def _add_template_parser(subparsers: Any) -> None:
    template_parser = subparsers.add_parser(
        "template",
        help="Manage loop templates",
    )
    template_sub = template_parser.add_subparsers(dest="template_command", required=True)

    # template list
    list_parser = template_sub.add_parser("list", help="List all templates")
    _add_format_option(list_parser)

    # template show
    show_parser = template_sub.add_parser("show", help="Show template details")
    show_parser.add_argument("name_or_id", help="Template name or ID")
    _add_format_option(show_parser)

    # template create
    create_parser = template_sub.add_parser("create", help="Create a template")
    create_parser.add_argument("name", help="Template name")
    create_parser.add_argument("--description", "-d", help="Template description")
    create_parser.add_argument("--pattern", "-p", default="", help="Raw text pattern")
    create_parser.add_argument("--tags", help="Comma-separated default tags")
    create_parser.add_argument("--time", type=int, help="Default time estimate (minutes)")
    create_parser.add_argument("--actionable", action="store_true", help="Default to actionable")
    _add_format_option(create_parser)

    # template delete
    delete_parser = template_sub.add_parser("delete", help="Delete a template")
    delete_parser.add_argument("name_or_id", help="Template name or ID")

    # template from-loop
    from_loop_parser = template_sub.add_parser("from-loop", help="Create template from loop")
    from_loop_parser.add_argument("loop_id", type=int, help="Loop ID")
    from_loop_parser.add_argument("name", help="Template name")
    _add_format_option(from_loop_parser)


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = get_settings()

    db.init_databases(settings)

    if args.command == "ingest":
        return _ingest_command(args, settings)
    if args.command == "ask":
        return _ask_command(args, settings)
    if args.command == "capture":
        return _capture_command(args, settings)
    if args.command == "inbox":
        return _inbox_command(args, settings)
    if args.command == "next":
        return _next_command(args, settings)

    if args.command == "loop":
        if args.loop_command == "get":
            return _loop_get_command(args, settings)
        if args.loop_command == "list":
            return _loop_list_command(args, settings)
        if args.loop_command == "search":
            return _loop_search_command(args, settings)
        if args.loop_command == "update":
            return _loop_update_command(args, settings)
        if args.loop_command == "status":
            return _loop_status_command(args, settings)
        if args.loop_command == "close":
            return _loop_close_command(args, settings)
        if args.loop_command == "enrich":
            return _loop_enrich_command(args, settings)
        if args.loop_command == "snooze":
            return _loop_snooze_command(args, settings)
        if args.loop_command == "view":
            if args.view_command == "create":
                return _loop_view_create_command(args, settings)
            if args.view_command == "list":
                return _loop_view_list_command(args, settings)
            if args.view_command == "get":
                return _loop_view_get_command(args, settings)
            if args.view_command == "update":
                return _loop_view_update_command(args, settings)
            if args.view_command == "delete":
                return _loop_view_delete_command(args, settings)
            if args.view_command == "apply":
                return _loop_view_apply_command(args, settings)
            parser.error(f"Unknown view command: {args.view_command}")
            return 2
        if args.loop_command == "claim":
            return _loop_claim_command(args, settings)
        if args.loop_command == "renew":
            return _loop_renew_claim_command(args, settings)
        if args.loop_command == "release":
            return _loop_release_claim_command(args, settings)
        if args.loop_command == "get-claim":
            return _loop_get_claim_command(args, settings)
        if args.loop_command == "claims":
            return _loop_list_claims_command(args, settings)
        if args.loop_command == "force-release":
            return _loop_force_release_claim_command(args, settings)
        if args.loop_command == "dep":
            return _loop_dep_command(args, settings)
        if args.loop_command == "timer":
            return _timer_command(args, settings)
        if args.loop_command == "sessions":
            return _sessions_command(args, settings)
        if args.loop_command == "review":
            return _review_command(args, settings)
        parser.error(f"Unknown loop command: {args.loop_command}")
        return 2

    if args.command == "template":
        if args.template_command == "list":
            return _template_list_command(args, settings)
        if args.template_command == "show":
            return _template_show_command(args, settings)
        if args.template_command == "create":
            return _template_create_command(args, settings)
        if args.template_command == "delete":
            return _template_delete_command(args, settings)
        if args.template_command == "from-loop":
            return _template_from_loop_command(args, settings)
        parser.error(f"Unknown template command: {args.template_command}")
        return 2

    if args.command == "tags":
        return _tags_command(args, settings)
    if args.command == "projects":
        return _projects_command(args, settings)
    if args.command == "export":
        return _export_command(args, settings)
    if args.command == "import":
        return _import_command(args, settings)
    if args.command == "backup":
        if args.backup_command == "create":
            return _backup_create_command(args, settings)
        if args.backup_command == "restore":
            return _backup_restore_command(args, settings)
        if args.backup_command == "list":
            return _backup_list_command(args, settings)
        if args.backup_command == "verify":
            return _backup_verify_command(args, settings)
        if args.backup_command == "rotate":
            return _backup_rotate_command(args, settings)
        parser.error(f"Unknown backup command: {args.backup_command}")
        return 2

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
