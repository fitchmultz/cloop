"""Chat command argument parser.

Purpose:
    Define the `cloop chat` CLI surface for grounded chat and tool-enabled chat
    requests.

Responsibilities:
    - Add the `chat` subcommand and its argument set
    - Expose grounded chat controls that map cleanly onto `ChatRequest`
    - Document transcript, streaming, and manual-tool examples in help text

Non-scope:
    - Chat execution
    - Input validation beyond argparse-level parsing
    - Output formatting
"""

from __future__ import annotations

from typing import Any

from .base import add_command_parser


def add_chat_parser(subparsers: Any) -> None:
    """Add `chat` command parser."""
    chat_parser = add_command_parser(
        subparsers,
        "chat",
        help_text="Run grounded chat from the CLI",
        description=(
            "Run pi-backed chat using the same grounded request/response contract "
            "as the HTTP /chat endpoint."
        ),
        examples="""
Examples:
  # One-shot grounded chat
  cloop chat "What should I focus on today?" --include-loop-context --include-memory-context

  # Stream tokens as they arrive
  cloop chat "Summarize my current priorities" --include-loop-context --stream

  # Add document grounding
  cloop chat "Where is the onboarding checklist?" --include-rag-context --rag-scope onboarding

  # Continue from a saved transcript JSON file
  cloop chat --messages-file transcript.json "What changed since the last update?"

  # Read the prompt from stdin explicitly
  printf 'What should I do next?\n' | cloop chat - --include-loop-context

  # Manual tool call from the CLI
  cloop chat "Create a loop" --tool loop_create --tool-arg raw_text='"Pay rent"'
        """,
    )
    chat_parser.add_argument(
        "prompt",
        nargs="?",
        help=(
            "Optional user prompt. Use '-' to read the prompt from stdin. "
            "If omitted and stdin is piped, stdin is used automatically."
        ),
    )
    chat_parser.add_argument(
        "--messages-file",
        help="Path to a JSON file containing an array of chat messages.",
    )
    chat_parser.add_argument(
        "--system-message",
        help="Optional system message prepended before the provided conversation.",
    )
    chat_parser.add_argument(
        "--tool-mode",
        choices=["manual", "llm", "none"],
        help="Tool mode to use for this request (default: none unless --tool is used).",
    )
    chat_parser.add_argument(
        "--tool",
        help="Manual tool name to invoke. Implies --tool-mode manual unless explicitly provided.",
    )
    chat_parser.add_argument(
        "--tool-arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Manual tool argument. Repeat as needed. VALUE is parsed as JSON when possible, "
            "otherwise treated as a string."
        ),
    )
    chat_parser.add_argument(
        "--tool-args-json",
        help="JSON object with manual tool arguments to merge before repeated --tool-arg values.",
    )
    chat_parser.add_argument(
        "--include-loop-context",
        action="store_true",
        help="Inject the current prioritized loop snapshot as system context.",
    )
    chat_parser.add_argument(
        "--include-memory-context",
        action="store_true",
        help="Inject stored memory entries as system context.",
    )
    chat_parser.add_argument(
        "--memory-limit",
        type=int,
        default=10,
        help="Max memory entries to include when --include-memory-context is set (default: 10).",
    )
    chat_parser.add_argument(
        "--include-rag-context",
        action="store_true",
        help="Retrieve relevant document chunks and inject them as chat context.",
    )
    chat_parser.add_argument(
        "--rag-k",
        type=int,
        default=5,
        help=(
            "Number of document chunks to retrieve when --include-rag-context is set (default: 5)."
        ),
    )
    chat_parser.add_argument(
        "--rag-scope",
        help="Restrict document grounding by path substring or doc:<id>.",
    )
    chat_parser.add_argument(
        "--stream",
        dest="stream",
        action="store_true",
        default=None,
        help="Stream tokens to stdout as they arrive.",
    )
    chat_parser.add_argument(
        "--no-stream",
        dest="stream",
        action="store_false",
        help="Disable streaming even if CLOOP_STREAM_DEFAULT is enabled.",
    )
    chat_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
