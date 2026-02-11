"""Health check response model."""

from typing import List

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response from /health endpoint showing service status."""

    ok: bool
    model: str
    vector_mode: str
    vector_backend: str
    core_db: str
    rag_db: str
    schema_version: int
    embed_storage: str
    tool_mode_default: str
    retrieval_order: List[str]
    retrieval_metric: str
