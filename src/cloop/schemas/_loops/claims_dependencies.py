"""Claim and dependency schemas for loops.

Purpose:
    Define request/response models for loop claims and dependency edges.

Responsibilities:
    - Validate claim lifecycle payloads
    - Define dependency create/read response envelopes
    - Keep concurrency and dependency schemas isolated from unrelated workflows

Non-scope:
    - Timer, template, or bulk-operation schemas
    - Core loop CRUD/search models
    - Claim/dependency business logic execution
"""

from __future__ import annotations

from ._shared import AUTHOR_MAX, BaseModel, Field


class LoopClaimRequest(BaseModel):
    """Request to claim a loop for exclusive access."""

    owner: str = Field(
        ..., min_length=1, max_length=AUTHOR_MAX, description="Identifier for claiming agent"
    )
    ttl_seconds: int | None = Field(default=None, ge=1, description="Lease duration in seconds")


class LoopRenewClaimRequest(BaseModel):
    """Request to renew an existing claim."""

    claim_token: str = Field(..., min_length=1, description="Token from original claim")
    ttl_seconds: int | None = Field(default=None, ge=1, description="New lease duration in seconds")


class LoopReleaseClaimRequest(BaseModel):
    """Request to release a claim."""

    claim_token: str = Field(..., min_length=1, description="Token from original claim")


class LoopClaimResponse(BaseModel):
    """Response for claim operations."""

    loop_id: int
    owner: str
    claim_token: str
    leased_at_utc: str
    lease_until_utc: str


class LoopClaimStatusResponse(BaseModel):
    """Claim status response (without token)."""

    loop_id: int
    owner: str
    leased_at_utc: str
    lease_until_utc: str


class DependencyAddRequest(BaseModel):
    """Request to add a dependency."""

    depends_on_loop_id: int = Field(..., description="Loop ID that this loop depends on")


class DependencyInfo(BaseModel):
    """Information about a dependency relationship."""

    id: int = Field(..., description="Loop ID")
    title: str = Field(..., description="Loop title or truncated raw_text")
    status: str = Field(..., description="Loop status")


class LoopWithDependenciesResponse(BaseModel):
    """Loop response with dependency information."""

    id: int
    raw_text: str
    title: str | None
    status: str
    dependencies: list[DependencyInfo] = Field(default_factory=list)
    blocking: list[DependencyInfo] = Field(default_factory=list)
    has_open_dependencies: bool = Field(
        default=False, description="True if loop has unclosed dependencies"
    )
