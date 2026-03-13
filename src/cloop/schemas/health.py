"""Health check response model.

Purpose:
    Define Pydantic models for health check endpoint responses.

Responsibilities:
    - Health status response schema
    - Dependency status reporting

Non-scope:
    - Health check logic (see main.py)
    - Database connectivity implementation (see db.py)
"""

from typing import Dict, List

from pydantic import BaseModel


class DependencyStatus(BaseModel):
    """Status of a single dependency (database, provider, etc.)."""

    ok: bool
    latency_ms: float
    error: str | None = None


class HealthResponse(BaseModel):
    """Response from /health endpoint showing service status."""

    ok: bool
    ai_backend: str
    chat_model: str
    organizer_model: str
    embed_model: str
    vector_mode: str
    vector_backend: str
    vector_available: bool
    vector_load_error: str | None = None
    core_db: str
    rag_db: str
    schema_version: int
    embed_storage: str
    tool_mode_default: str
    retrieval_order: List[str]
    retrieval_metric: str
    checks: Dict[str, DependencyStatus]
