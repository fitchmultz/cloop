"""RAG (Retrieval-Augmented Generation) request/response models.

Purpose:
    Define Pydantic models for document ingestion and QA endpoints.

Responsibilities:
    - Ingest request/response schemas
    - Query request/response schemas

Non-scope:
    - Document storage logic (see rag/documents.py)
    - Search algorithms (see rag/search.py)

Models for document ingestion and question-answering endpoints.
"""

from enum import StrEnum
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ._loops.continuity import ContinuityRerunAction, ReviewFollowThroughResponse


class IngestMode(StrEnum):
    """Document ingestion mode."""

    ADD = "add"
    REINDEX = "reindex"
    PURGE = "purge"
    SYNC = "sync"


class IngestRequest(BaseModel):
    """Request to ingest documents into the knowledge base."""

    paths: List[str]
    mode: IngestMode | None = Field(
        default=None,
        description="Ingestion mode: add, reindex, purge, or sync. Defaults to add.",
    )
    recursive: bool | None = Field(
        default=None,
        description="Recurse into directories when true (default).",
    )
    working_set_id: int | None = Field(
        default=None,
        ge=1,
        description="Optional working-set scope to preserve in ingest follow-through payloads.",
    )
    query: str | None = Field(
        default=None,
        description="Optional recall query to preserve on the landed ingest resume target.",
    )


class FailedFileInfo(BaseModel):
    """Information about a file that failed to ingest."""

    path: str
    error: str


class IngestResponse(BaseModel):
    """Response from document ingestion."""

    files: int
    chunks: int
    files_skipped: int = 0
    failed_files: List[FailedFileInfo] = Field(default_factory=list)
    follow_through: ReviewFollowThroughResponse | None = None


class AskResponse(BaseModel):
    """Response from RAG question-answering."""

    answer: str
    chunks: List[Dict[str, Any]]
    model: str | None = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    rerun_action: ContinuityRerunAction | None = None
    follow_through: ReviewFollowThroughResponse | None = None
