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

from pydantic import BaseModel, Field


class DependencyStatus(BaseModel):
    """Status of a single dependency (database, provider, etc.)."""

    ok: bool
    latency_ms: float
    error: str | None = None


class SelectorResolutionResponse(BaseModel):
    """Resolved runtime selector metadata for one AI role."""

    requested_selector: str
    requested_selectors: list[str] = Field(default_factory=list)
    resolved_selector: str | None = None
    fallback_used: bool = False
    selector_mode: str
    error: str | None = None


class HealthResponse(BaseModel):
    """Response from /health endpoint showing service status."""

    ok: bool
    ai_backend: str
    chat_selector: SelectorResolutionResponse
    organizer_selector: SelectorResolutionResponse
    embed_model: str
    bridge_name: str | None = None
    bridge_version: str | None = None
    bridge_protocol: int | None = None
    vector_mode: str
    vector_backend: str
    vector_available: bool
    vector_load_error: str | None = None
    core_db: str
    rag_db: str
    schema_version: int
    embed_storage: str
    tool_mode_default: str
    retrieval_order: list[str]
    retrieval_metric: str
    checks: dict[str, DependencyStatus]
