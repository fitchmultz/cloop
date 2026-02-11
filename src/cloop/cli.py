import argparse
import json
import sys
from datetime import datetime
from typing import Any, Dict, List

from . import db
from .constants import DEFAULT_LOOP_LIST_LIMIT, DEFAULT_LOOP_NEXT_LIMIT
from .loops.models import LoopStatus, resolve_status_from_flags
from .loops.service import capture_loop, list_loops, next_loops, request_enrichment
from .rag import ingest_paths, retrieve_similar_chunks
from .settings import Settings, get_settings


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloop")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    ask_parser = subparsers.add_parser("ask", help="Query the knowledge base")
    ask_parser.add_argument("question", help="Question text")
    ask_parser.add_argument("--k", type=int, default=5, help="Top-k chunks to retrieve")
    ask_parser.add_argument(
        "--scope",
        help="Restrict retrieval by path substring or doc:<id>",
    )

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

    inbox_parser = subparsers.add_parser("inbox", help="List inbox loops")
    inbox_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LOOP_LIST_LIMIT, help="Max loops to return"
    )

    next_parser = subparsers.add_parser("next", help="Show the next loops")
    next_parser.add_argument(
        "--limit", type=int, default=DEFAULT_LOOP_NEXT_LIMIT, help="Max loops per bucket"
    )

    return parser


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
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
