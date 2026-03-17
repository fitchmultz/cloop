"""Saved-view and webhook schemas for loops.

Purpose:
    Define saved-view, loop-event-stream, and webhook request/response models.

Responsibilities:
    - Validate saved-view payloads
    - Shape loop event stream responses
    - Validate and serialize webhook subscription payloads

Non-scope:
    - Core loop CRUD/search schemas
    - Review-session, planning, or suggestion models
    - Webhook delivery execution logic
"""

from __future__ import annotations

from typing import Any, Dict, List

from ._shared import (
    SEARCH_QUERY_MAX,
    VIEW_DESCRIPTION_MAX,
    VIEW_NAME_MAX,
    WEBHOOK_DESCRIPTION_MAX,
    WEBHOOK_URL_MAX,
    BaseModel,
    Field,
    field_validator,
    validate_http_url_field,
)
from .core import LoopResponse


class LoopViewCreateRequest(BaseModel):
    """Request to create a saved view."""

    name: str = Field(..., min_length=1, max_length=VIEW_NAME_MAX, description="View name")
    query: str = Field(
        ..., min_length=1, max_length=SEARCH_QUERY_MAX, description="DSL query string"
    )
    description: str | None = Field(
        default=None, max_length=VIEW_DESCRIPTION_MAX, description="Optional description"
    )


class LoopViewUpdateRequest(BaseModel):
    """Request to update a saved view."""

    name: str | None = Field(default=None, min_length=1, max_length=VIEW_NAME_MAX)
    query: str | None = Field(default=None, min_length=1, max_length=SEARCH_QUERY_MAX)
    description: str | None = Field(default=None, max_length=VIEW_DESCRIPTION_MAX)


class LoopViewResponse(BaseModel):
    """Saved view response."""

    id: int
    name: str
    query: str
    description: str | None = None
    created_at_utc: str
    updated_at_utc: str


class LoopViewApplyResponse(BaseModel):
    """Response from applying a saved view."""

    view: LoopViewResponse
    query: str
    limit: int
    offset: int
    items: List[LoopResponse]


class LoopEventStreamResponse(BaseModel):
    """SSE event envelope for loop events."""

    event_id: int
    event_type: str
    loop_id: int
    payload: Dict[str, Any]
    timestamp: str


class WebhookSubscriptionCreate(BaseModel):
    """Request to create a webhook subscription."""

    url: str = Field(
        ..., min_length=1, max_length=WEBHOOK_URL_MAX, description="Webhook URL (https recommended)"
    )
    event_types: List[str] = Field(
        default=["*"], description="Event types to subscribe to, ['*'] for all"
    )
    description: str | None = Field(
        default=None, max_length=WEBHOOK_DESCRIPTION_MAX, description="Optional description"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must use http or https")
        return v


class WebhookSubscriptionUpdate(BaseModel):
    """Request to update a webhook subscription."""

    url: str | None = Field(default=None, min_length=1, max_length=WEBHOOK_URL_MAX)
    event_types: List[str] | None = None
    active: bool | None = None
    description: str | None = Field(default=None, max_length=WEBHOOK_DESCRIPTION_MAX)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        return validate_http_url_field(v)


class WebhookSubscriptionResponse(BaseModel):
    """Webhook subscription response."""

    id: int
    url: str
    event_types: List[str]
    active: bool
    description: str | None
    created_at_utc: str
    updated_at_utc: str


class WebhookSubscriptionCreateResponse(BaseModel):
    """Webhook subscription creation response.

    Includes the secret that was generated - this is the ONLY time
    the secret will be returned. Store it securely for signature verification.
    """

    id: int
    url: str
    event_types: List[str]
    active: bool
    description: str | None
    created_at_utc: str
    updated_at_utc: str
    secret: str


class WebhookDeliveryResponse(BaseModel):
    """Webhook delivery response."""

    id: int
    subscription_id: int
    event_id: int
    event_type: str
    status: str
    http_status: int | None
    error_message: str | None
    attempt_count: int
    next_retry_at: str | None
    created_at_utc: str
    updated_at_utc: str
