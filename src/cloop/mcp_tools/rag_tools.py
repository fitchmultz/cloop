"""RAG MCP tools.

Purpose:
    Expose knowledge-base ingestion and retrieval to MCP clients through the
    same shared RAG execution contract used by HTTP and CLI surfaces.

Responsibilities:
    - Provide `rag.ask` for grounded retrieval + answer generation
    - Provide `rag.ingest` for document indexing and knowledge-base refresh
    - Keep MCP transport details thin by delegating to shared execution
    - Convert domain/runtime failures into MCP `ToolError` responses

Tools:
    - rag.ask: Ask a question against the local knowledge base
    - rag.ingest: Ingest files or directories into the local knowledge base

Non-scope:
    - Loop lifecycle or suggestion tools
    - Document chunking, embeddings, or vector search internals
    - MCP server assembly
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..rag_execution import execute_ask_request, execute_ingest_request
from ..settings import get_settings
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
def rag_ask(
    question: str,
    top_k: int | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Ask a question against the local knowledge base.

    Retrieves the most relevant chunks from the indexed knowledge base and,
    when knowledge is available, generates an answer using the shared RAG ask
    execution contract. If no knowledge is available yet, the tool returns the
    shared fallback answer instead of failing.

    Args:
        question: Natural-language question to answer from indexed documents.
        top_k: Optional number of chunks to retrieve. Defaults to the configured
            `CLOOP_DEFAULT_TOP_K` value when omitted.
        scope: Optional retrieval restriction by path substring or `doc:<id>`.

    Returns:
        Dict with:
        - answer: Final answer text or the shared no-knowledge fallback
        - chunks: Sanitized retrieved chunks used for grounding
        - model: Generative model name when an answer was generated
        - sources: Source references derived from the retrieved chunks

    Raises:
        ToolError: If retrieval or answer generation fails, or if `top_k` is invalid.
    """
    settings = get_settings()
    result = execute_ask_request(
        question=question,
        top_k=settings.default_top_k if top_k is None else top_k,
        scope=scope,
        settings=settings,
        endpoint="/mcp/rag.ask",
    )
    return result.response.model_dump(mode="json")


@with_mcp_error_handling
def rag_ingest(
    paths: list[str],
    mode: str = "add",
    recursive: bool = True,
    force_rehash: bool = False,
) -> dict[str, Any]:
    """Ingest files or directories into the local knowledge base.

    The tool walks the provided paths, loads supported files, chunks content,
    computes embeddings, and updates the local RAG store using the shared
    ingest execution contract.

    Args:
        paths: File and/or directory paths to ingest. Must not be empty.
        mode: Ingestion mode.
            - `add`: add new/changed content only
            - `reindex`: recompute embeddings for matched content
            - `purge`: remove matching content from the knowledge base
            - `sync`: ingest current matches and purge tracked files that no longer exist
        recursive: Whether directory inputs should be traversed recursively.
        force_rehash: Whether to recompute file hashes even when mtime/size are unchanged.

    Returns:
        Dict with:
        - files: Count of processed files or removed documents
        - chunks: Count of stored or removed chunks
        - files_skipped: Count of unchanged files skipped during ingest
        - failed_files: List of failed file records with `path` and `error`

    Raises:
        ToolError: If validation fails or ingestion encounters an execution error.
    """
    settings = get_settings()
    result = execute_ingest_request(
        paths=paths,
        mode=mode,
        recursive=recursive,
        force_rehash=force_rehash,
        settings=settings,
        endpoint="/mcp/rag.ingest",
    )
    return result.response_payload


def register_rag_tools(mcp: "FastMCP") -> None:
    """Register RAG tools with the MCP server."""
    from ._runtime import with_db_init

    mcp.tool(name="rag.ask")(with_db_init(rag_ask))
    mcp.tool(name="rag.ingest")(with_db_init(rag_ingest))
