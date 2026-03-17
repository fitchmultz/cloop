"""Shared loop-schema helpers and imports.

Purpose:
    Centralize common imports and reusable validators for loop-related Pydantic schemas.

Responsibilities:
    - Export shared typing/Pydantic building blocks for loop schema modules
    - Provide reusable field validators for timestamps, due dates, offsets, and webhook URLs
    - Keep workflow-specific schema files focused on model declarations

Non-scope:
    - Declaring workflow/domain response models directly
    - Business-rule orchestration beyond field validation
    - Transport-specific route or serialization logic outside schema concerns
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from ...constants import (
    AUTHOR_MAX,
    BLOCKED_REASON_MAX,
    BULK_OPERATION_MAX_ITEMS,
    COMMENT_BODY_MAX,
    COMPLETION_NOTE_MAX,
    DEFINITION_OF_DONE_MAX,
    NEXT_ACTION_MAX,
    PROJECT_MAX,
    RAW_TEXT_MAX,
    RRULE_MAX,
    SCHEDULE_MAX,
    SEARCH_QUERY_MAX,
    SUMMARY_MAX,
    TEMPLATE_DESCRIPTION_MAX,
    TEMPLATE_NAME_MAX,
    TIMEZONE_MAX,
    TITLE_MAX,
    VIEW_DESCRIPTION_MAX,
    VIEW_NAME_MAX,
    WEBHOOK_DESCRIPTION_MAX,
    WEBHOOK_URL_MAX,
)
from ...loops.due_contract import validate_due_date
from ...loops.models import LoopStatus

__all__ = [
    "AUTHOR_MAX",
    "BLOCKED_REASON_MAX",
    "BULK_OPERATION_MAX_ITEMS",
    "COMMENT_BODY_MAX",
    "COMPLETION_NOTE_MAX",
    "DEFINITION_OF_DONE_MAX",
    "NEXT_ACTION_MAX",
    "PROJECT_MAX",
    "RAW_TEXT_MAX",
    "RRULE_MAX",
    "SCHEDULE_MAX",
    "SEARCH_QUERY_MAX",
    "SUMMARY_MAX",
    "TEMPLATE_DESCRIPTION_MAX",
    "TEMPLATE_NAME_MAX",
    "TIMEZONE_MAX",
    "TITLE_MAX",
    "VIEW_DESCRIPTION_MAX",
    "VIEW_NAME_MAX",
    "WEBHOOK_DESCRIPTION_MAX",
    "WEBHOOK_URL_MAX",
    "BaseModel",
    "Field",
    "LoopStatus",
    "field_validator",
    "validate_due_date",
    "validate_http_url_field",
]


def validate_http_url_field(value: str | None) -> str | None:
    """Validate that a webhook URL uses HTTP or HTTPS."""
    if value is not None and not value.startswith(("http://", "https://")):
        raise ValueError("URL must use http or https")
    return value
