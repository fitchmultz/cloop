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
from .loops.errors import LoopNotFoundError, TransitionError, ValidationError
from .loops.models import (
    LoopStatus,
    format_utc_datetime,
    resolve_status_from_flags,
    utc_now,
    validate_iso8601_timestamp,
)
from .loops.service import (
    apply_loop_view,
    capture_loop,
    create_loop_view,
    delete_loop_view,
    export_loops,
    get_loop,
    get_loop_view,
    import_loops,
    list_loop_views,
    list_loops,
    list_loops_by_statuses,
    list_loops_by_tag,
    list_tags,
    next_loops,
    request_enrichment,
    search_loops_by_query,
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

    with db.core_connection(settings) as conn:
        record = capture_loop(
            raw_text=args.text,
            captured_at_iso=captured_at,
            client_tz_offset_min=tz_offset_min,
            status=status,
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

    try:
        with db.core_connection(settings) as conn:
            record = update_loop(loop_id=args.id, fields=fields, conn=conn)
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _loop_status_command(args: argparse.Namespace, settings: Settings) -> int:
    try:
        to_status = LoopStatus(args.status)
    except ValueError:
        print(f"error: invalid status '{args.status}'", file=sys.stderr)
        return 1

    try:
        with db.core_connection(settings) as conn:
            record = transition_status(
                loop_id=args.id,
                to_status=to_status,
                conn=conn,
                note=args.note,
            )
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
    except TransitionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def _loop_close_command(args: argparse.Namespace, settings: Settings) -> int:
    to_status = LoopStatus.DROPPED if args.dropped else LoopStatus.COMPLETED

    try:
        with db.core_connection(settings) as conn:
            record = transition_status(
                loop_id=args.id,
                to_status=to_status,
                conn=conn,
                note=args.note,
            )
        _emit_output(record, args.format)
        return 0
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2
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

  # Data portability
  cloop export --output backup.json
  cloop import --file backup.json

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

    _add_tags_parser(subparsers)
    _add_projects_parser(subparsers)
    _add_export_parser(subparsers)
    _add_import_parser(subparsers)

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
    _add_format_option(status_parser)

    close_parser = loop_subparsers.add_parser("close", help="Close a loop")
    close_parser.add_argument("id", type=int, help="Loop ID")
    close_parser.add_argument(
        "--dropped",
        action="store_true",
        help="Close as dropped instead of completed",
    )
    close_parser.add_argument("--note", help="Completion/drop note")
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
        parser.error(f"Unknown loop command: {args.loop_command}")
        return 2

    if args.command == "tags":
        return _tags_command(args, settings)
    if args.command == "projects":
        return _projects_command(args, settings)
    if args.command == "export":
        return _export_command(args, settings)
    if args.command == "import":
        return _import_command(args, settings)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
