"""RAG command argument parsers.

Purpose:
    Argument parsers for ingest and ask commands.
"""

from __future__ import annotations

from typing import Any


def add_ingest_parser(subparsers: Any) -> None:
    """Add 'ingest' command parser."""
    from argparse import RawDescriptionHelpFormatter

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest documents",
        description="Ingest documents into the knowledge base",
        epilog="""
Examples:
  # Ingest a single file
  cloop ingest /path/to/document.md

  # Ingest a directory recursively
  cloop ingest ~/Documents/my-notes

  # Ingest with reindex mode (replaces existing)
  cloop ingest ~/notes --mode reindex

  # Ingest without recursion
  cloop ingest ~/notes --no-recursive

  # Ingest multiple paths
  cloop ingest doc1.md doc2.md ~/notes
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
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
    ingest_parser.add_argument(
        "--force-rehash",
        action="store_true",
        help="Force SHA256 recomputation for all files (ignores mtime/size cache)",
    )


def add_ask_parser(subparsers: Any) -> None:
    """Add 'ask' command parser."""
    from argparse import RawDescriptionHelpFormatter

    ask_parser = subparsers.add_parser(
        "ask",
        help="Query the knowledge base",
        description="Query the knowledge base using semantic search",
        epilog="""
Examples:
  # Basic question
  cloop ask "What is the deployment process?"

  # Retrieve more chunks
  cloop ask "API authentication" --k 10

  # Restrict to specific document
  cloop ask "architecture" --scope doc:123

  # Restrict by path substring
  cloop ask "meeting notes" --scope "2026-02"
        """,
        formatter_class=RawDescriptionHelpFormatter,
    )
    ask_parser.add_argument("question", help="Question text")
    ask_parser.add_argument("--k", type=int, default=5, help="Top-k chunks to retrieve")
    ask_parser.add_argument(
        "--scope",
        help="Restrict retrieval by path substring or doc:<id>",
    )
