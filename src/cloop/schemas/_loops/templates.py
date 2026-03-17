"""Loop template schemas.

Purpose:
    Define request/response models for reusable loop templates.

Responsibilities:
    - Validate template create/update payloads
    - Shape template list and detail responses
    - Keep template contracts independent from other loop workflows

Non-scope:
    - Template persistence or application logic
    - Review, planning, or suggestion schemas
    - Core loop capture/update payloads
"""

from __future__ import annotations

from typing import Any, Dict, List

from ._shared import RAW_TEXT_MAX, TEMPLATE_DESCRIPTION_MAX, TEMPLATE_NAME_MAX, BaseModel, Field


class LoopTemplateResponse(BaseModel):
    """Response model for a loop template."""

    id: int
    name: str
    description: str | None
    raw_text_pattern: str
    defaults: Dict[str, Any]
    is_system: bool
    created_at: str
    updated_at: str


class LoopTemplateCreateRequest(BaseModel):
    """Request to create a new loop template."""

    name: str = Field(..., min_length=1, max_length=TEMPLATE_NAME_MAX)
    description: str | None = Field(default=None, max_length=TEMPLATE_DESCRIPTION_MAX)
    raw_text_pattern: str = Field(default="", max_length=RAW_TEXT_MAX)
    defaults: Dict[str, Any] = Field(default_factory=dict)


class LoopTemplateUpdateRequest(BaseModel):
    """Request to update a loop template."""

    name: str | None = Field(default=None, min_length=1, max_length=TEMPLATE_NAME_MAX)
    description: str | None = Field(default=None, max_length=TEMPLATE_DESCRIPTION_MAX)
    raw_text_pattern: str | None = Field(default=None, max_length=RAW_TEXT_MAX)
    defaults: Dict[str, Any] | None = None


class LoopTemplateListResponse(BaseModel):
    """Response for listing templates."""

    templates: List[LoopTemplateResponse]
