"""Common utilities for loop routes.

Purpose:
    Shared dependencies, types, and helper functions used across
    all loop route modules.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from ...settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]
IdempotencyKeyHeader = Header(default=None, alias="Idempotency-Key")


def _idempotency_conflict(detail: str) -> HTTPException:
    """Create an HTTPException for idempotency key conflicts."""
    return HTTPException(
        status_code=409,
        detail={"message": "idempotency_key_conflict", "detail": detail},
    )
