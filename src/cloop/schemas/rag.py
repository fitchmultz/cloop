"""RAG (Retrieval-Augmented Generation) request/response models.

Models for document ingestion and question-answering endpoints.
"""

from enum import StrEnum
from typing import Any, Dict, List

from pydantic import BaseModel, Field


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


class FailedFileInfo(BaseModel):
    """Information about a file that failed to ingest."""

    path: str
    error: str


class IngestResponse(BaseModel):
    """Response from document ingestion."""

    files: int
    chunks: int
    failed_files: List[FailedFileInfo] = Field(default_factory=list)


class AskResponse(BaseModel):
    """Response from RAG question-answering."""

    answer: str
    chunks: List[Dict[str, Any]]
    model: str | None = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
