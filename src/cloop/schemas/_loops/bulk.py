"""Bulk mutation schemas for loop workflows.

Purpose:
    Define per-item and query-targeted bulk mutation request/response models.

Responsibilities:
    - Validate bulk update/close/snooze/enrich payloads
    - Shape per-item and aggregate bulk results
    - Keep query-targeted bulk contracts aligned with shared loop responses

Non-scope:
    - Executing bulk mutations or transaction logic
    - Saved review sessions or planning schemas
    - Core loop CRUD/search models outside bulk flows
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from ._shared import (
    BULK_OPERATION_MAX_ITEMS,
    COMPLETION_NOTE_MAX,
    SEARCH_QUERY_MAX,
    BaseModel,
    Field,
    LoopStatus,
    field_validator,
)
from .core import LoopResponse, LoopUpdateRequest


class BulkUpdateItem(BaseModel):
    """Single item in a bulk update request."""

    loop_id: int
    fields: LoopUpdateRequest


class BulkCloseItem(BaseModel):
    """Single item in a bulk close request."""

    loop_id: int
    status: Literal[LoopStatus.COMPLETED, LoopStatus.DROPPED] = LoopStatus.COMPLETED
    note: str | None = Field(default=None, max_length=COMPLETION_NOTE_MAX)


class BulkSnoozeItem(BaseModel):
    """Single item in a bulk snooze request."""

    loop_id: int
    snooze_until_utc: str

    @field_validator("snooze_until_utc", mode="before")
    @classmethod
    def validate_snooze_until_utc(cls, v: str) -> str:
        from ...loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "snooze_until_utc")


class BulkUpdateRequest(BaseModel):
    """Request for bulk loop update."""

    updates: List[BulkUpdateItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of updates (max {BULK_OPERATION_MAX_ITEMS} items)",
    )
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkCloseRequest(BaseModel):
    """Request for bulk loop close."""

    items: List[BulkCloseItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of items to close (max {BULK_OPERATION_MAX_ITEMS} items)",
    )
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkSnoozeRequest(BaseModel):
    """Request for bulk loop snooze."""

    items: List[BulkSnoozeItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of items to snooze (max {BULK_OPERATION_MAX_ITEMS} items)",
    )
    transactional: bool = Field(default=False, description="Rollback all on any failure")


class BulkEnrichItem(BaseModel):
    """Single item in a bulk enrich request."""

    loop_id: int


class BulkEnrichRequest(BaseModel):
    """Request for bulk loop enrichment."""

    items: List[BulkEnrichItem] = Field(
        ...,
        min_length=1,
        max_length=BULK_OPERATION_MAX_ITEMS,
        description=f"List of loops to enrich (max {BULK_OPERATION_MAX_ITEMS} items)",
    )


class BulkResultItem(BaseModel):
    """Result for a single item in bulk operation."""

    index: int
    loop_id: int
    ok: bool
    loop: LoopResponse | None = None
    error: Dict[str, Any] | None = None


class BulkEnrichmentResultItem(BulkResultItem):
    """Result for one loop inside a bulk enrichment run."""

    suggestion_id: int | None = None
    applied_fields: List[str] = Field(default_factory=list)
    needs_clarification: List[str] = Field(default_factory=list)


class BulkUpdateResponse(BaseModel):
    """Response for bulk update operation."""

    ok: bool
    transactional: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class BulkCloseResponse(BaseModel):
    """Response for bulk close operation."""

    ok: bool
    transactional: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class BulkSnoozeResponse(BaseModel):
    """Response for bulk snooze operation."""

    ok: bool
    transactional: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class BulkEnrichResponse(BaseModel):
    """Response for bulk enrichment operation."""

    ok: bool
    results: List[BulkEnrichmentResultItem]
    succeeded: int
    failed: int


class QueryBulkUpdateRequest(BaseModel):
    """Bulk update targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    fields: LoopUpdateRequest = Field(..., description="Fields to update on matched loops")
    transactional: bool = Field(default=False, description="Rollback all on any failure")
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100, ge=1, le=BULK_OPERATION_MAX_ITEMS, description="Max loops to affect"
    )


class QueryBulkCloseRequest(BaseModel):
    """Bulk close targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    status: Literal[LoopStatus.COMPLETED, LoopStatus.DROPPED] = LoopStatus.COMPLETED
    note: str | None = Field(default=None, max_length=COMPLETION_NOTE_MAX)
    transactional: bool = Field(default=False, description="Rollback all on any failure")
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100, ge=1, le=BULK_OPERATION_MAX_ITEMS, description="Max loops to affect"
    )


class QueryBulkSnoozeRequest(BaseModel):
    """Bulk snooze targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    snooze_until_utc: str = Field(..., description="Snooze until timestamp")
    transactional: bool = Field(default=False, description="Rollback all on any failure")
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100, ge=1, le=BULK_OPERATION_MAX_ITEMS, description="Max loops to affect"
    )

    @field_validator("snooze_until_utc", mode="before")
    @classmethod
    def validate_snooze_until_utc(cls, v: str) -> str:
        from ...loops.models import validate_iso8601_timestamp

        return validate_iso8601_timestamp(v, "snooze_until_utc")


class QueryBulkEnrichRequest(BaseModel):
    """Bulk enrich targeting loops by DSL query."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=SEARCH_QUERY_MAX,
        description="DSL query to select target loops",
    )
    dry_run: bool = Field(default=False, description="Preview targets without applying changes")
    limit: int = Field(
        default=100,
        ge=1,
        le=BULK_OPERATION_MAX_ITEMS,
        description="Max loops to affect",
    )


class QueryBulkPreviewResponse(BaseModel):
    """Response for dry-run preview of query-based bulk operation."""

    query: str
    dry_run: bool
    matched_count: int
    limited: bool
    targets: List[LoopResponse]


class QueryBulkUpdateResponse(BaseModel):
    """Response for query-based bulk update."""

    query: str
    dry_run: bool
    ok: bool
    transactional: bool
    matched_count: int
    limited: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class QueryBulkCloseResponse(BaseModel):
    """Response for query-based bulk close."""

    query: str
    dry_run: bool
    ok: bool
    transactional: bool
    matched_count: int
    limited: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class QueryBulkSnoozeResponse(BaseModel):
    """Response for query-based bulk snooze."""

    query: str
    dry_run: bool
    ok: bool
    transactional: bool
    matched_count: int
    limited: bool
    results: List[BulkResultItem]
    succeeded: int
    failed: int


class QueryBulkEnrichResponse(BaseModel):
    """Response for query-based bulk enrichment."""

    query: str
    dry_run: bool
    ok: bool
    matched_count: int
    limited: bool
    results: List[BulkEnrichmentResultItem]
    succeeded: int
    failed: int
