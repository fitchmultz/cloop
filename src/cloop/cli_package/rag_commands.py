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

from ..rag import NO_KNOWLEDGE_MESSAGE, answer_question, ingest_paths
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
    answer = answer_question(
        question=args.question,
        top_k=args.k,
        scope=args.scope,
        settings=settings,
    )
    if answer.answer == NO_KNOWLEDGE_MESSAGE:
        print(NO_KNOWLEDGE_MESSAGE, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "answer": answer.answer,
                "chunks": answer.chunks,
                "model": answer.model,
                "sources": answer.sources,
            },
            indent=2,
        )
    )
    return 0
