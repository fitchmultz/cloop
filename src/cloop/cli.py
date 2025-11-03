from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from . import db
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
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
