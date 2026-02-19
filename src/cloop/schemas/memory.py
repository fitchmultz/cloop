"""Assistant memory entry request/response models.

Purpose:
    Define Pydantic models for the /memory/* endpoints.

Responsibilities:
    - Memory CRUD request/response schemas
    - Category and source validation

Non-scope:
    - Database operations (see db.py)
    - HTTP route handlers (see routes/memory.py)
"""

from enum import StrEnum
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..constants import MEMORY_CONTENT_MAX, MEMORY_KEY_MAX


class MemoryCategory(StrEnum):
    """Memory entry categories for semantic organization."""

    PREFERENCE = "preference"
    FACT = "fact"
    COMMITMENT = "commitment"
    CONTEXT = "context"


class MemorySource(StrEnum):
    """Memory entry origin for trust weighting."""

    USER_STATED = "user_stated"
    INFERRED = "inferred"
    IMPORTED = "imported"
    SYSTEM = "system"


class MemoryEntryBase(BaseModel):
    """Base fields for memory entry."""

    key: str | None = Field(
        default=None,
        max_length=MEMORY_KEY_MAX,
        description="Optional natural-language identifier for semantic lookup",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=MEMORY_CONTENT_MAX,
        description="The memory content/value",
    )
    category: MemoryCategory = Field(
        default=MemoryCategory.FACT,
        description="Semantic category for organization",
    )
    priority: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Retrieval priority (higher = more important)",
    )
    source: MemorySource = Field(
        default=MemorySource.USER_STATED,
        description="Origin of this memory",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured metadata",
    )


class MemoryCreateRequest(MemoryEntryBase):
    """Request to create a new memory entry."""

    pass


class MemoryUpdateRequest(BaseModel):
    """Request to update an existing memory entry."""

    key: str | None = Field(default=None, max_length=MEMORY_KEY_MAX)
    content: str | None = Field(default=None, min_length=1, max_length=MEMORY_CONTENT_MAX)
    category: MemoryCategory | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    source: MemorySource | None = None
    metadata: Dict[str, Any] | None = None


class MemoryResponse(BaseModel):
    """Response for a single memory entry."""

    id: int
    key: str | None
    content: str
    category: MemoryCategory
    priority: int
    source: MemorySource
    metadata: Dict[str, Any]
    created_at: str
    updated_at: str


class MemoryListResponse(BaseModel):
    """Response for memory list/search."""

    items: List[MemoryResponse]
    next_cursor: str | None = None
    limit: int
