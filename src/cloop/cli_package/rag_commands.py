"""RAG command handlers.

Purpose:
    Implement CLI command handlers for RAG operations (ingest, ask).

Responsibilities:
    - Handle ingest and ask commands
    - Call RAG service layer
    - Format output

Non-scope:
    - Does not implement embedding generation (handled by RAG service)
    - Does not manage vector storage directly (abstracted in RAG module)
    - Does not handle document parsing logic (handled by ingest layer)
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from typing import Any, Dict

from ..rag import ingest_paths, retrieve_similar_chunks
from ..settings import Settings


def ingest_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop ingest' command."""
    result = ingest_paths(
        args.paths,
        mode=args.mode,
        recursive=not args.no_recursive,
        force_rehash=args.force_rehash,
        settings=settings,
    )
    print(json.dumps(result, indent=2))
    return 0


def ask_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop ask' command."""
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
