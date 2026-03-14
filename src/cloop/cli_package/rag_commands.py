"""RAG command handlers.

Purpose:
    Implement CLI command handlers for shared RAG ingest and ask flows.

Responsibilities:
    - Handle ingest and ask commands
    - Delegate execution to the shared RAG execution contract
    - Format JSON output or no-knowledge fallback messaging

Non-scope:
    - Embedding generation or vector search internals
    - HTTP/SSE transport behavior
    - CLI argument parsing
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace

from ..rag import NO_KNOWLEDGE_MESSAGE
from ..rag_execution import execute_ask_request, execute_ingest_request
from ..settings import Settings


def ingest_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop ingest' command."""
    result = execute_ingest_request(
        paths=list(args.paths),
        mode=args.mode,
        recursive=not args.no_recursive,
        force_rehash=args.force_rehash,
        settings=settings,
        endpoint="/cli/ingest",
    )
    print(json.dumps(result.response_payload, indent=2))
    return 0


def ask_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop ask' command."""
    result = execute_ask_request(
        question=args.question,
        top_k=args.k,
        scope=args.scope,
        settings=settings,
        endpoint="/cli/ask",
    )
    if result.response.answer == NO_KNOWLEDGE_MESSAGE:
        print(NO_KNOWLEDGE_MESSAGE, file=sys.stderr)
        return 1
    print(json.dumps(result.response.model_dump(mode="json"), indent=2))
    return 0
