"""Common utilities for loop routes.

Purpose:
    Shared dependencies, types, and helper functions used across
    all loop route modules.

Responsibilities:
    - Define common FastAPI dependencies (SettingsDep)
    - Define idempotency key header parameter
    - Provide helper for idempotency conflict HTTP exceptions

Non-scope:
    - Does not contain endpoint implementations
    - Does not define Pydantic schemas or request/response models
    - Does not interact with database directly
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from ...settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]
IdempotencyKeyHeader = Header(
    default=None,
    alias="Idempotency-Key",
    description=(
        "Unique key for idempotent requests. Re-sending the same request "
        "with this key returns the original response. "
        "Format: UUID v4 or prefixed UUID (e.g., 'req_550e8400-e29b-41d4-a716-446655440000'). "
        "Max length: 255 characters."
    ),
)


def _idempotency_conflict(detail: str) -> HTTPException:
    """Create an HTTPException for idempotency key conflicts."""
    return HTTPException(
        status_code=409,
        detail={"message": "idempotency_key_conflict", "detail": detail},
    )
