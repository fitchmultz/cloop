"""Life feed endpoints.

Purpose:
    Expose the simple product-facing Life conversation layer.

Responsibilities:
    - POST /life/message for capture, resurfacing, cleanup, and preference memory
    - Keep HTTP transport thin over `life_orchestration`

Non-scope:
    - Loop CRUD endpoints, direct memory management, or provider-backed chat
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from .. import db
from ..life_orchestration import handle_life_message
from ..schemas.life import LifeMessageRequest, LifeMessageResponse
from ..settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]

router = APIRouter(prefix="/life", tags=["life"])


@router.post("/message", response_model=LifeMessageResponse)
def life_message_endpoint(
    request: LifeMessageRequest, settings: SettingsDep
) -> LifeMessageResponse:
    """Handle one natural-language Life feed message."""
    with db.core_connection(settings) as conn:
        return handle_life_message(
            message=request.message,
            settings=settings,
            conn=conn,
            captured_at=request.captured_at,
            client_tz_offset_min=request.client_tz_offset_min,
            external_inputs=request.external_inputs,
        )
