"""FastAPI routes for web push notification management.

Purpose:
    Expose HTTP endpoints for push subscription and VAPID key retrieval.

Responsibilities:
    - GET /push/vapid_public_key: Return VAPID public key
    - POST /push/subscribe: Store client push subscription

Non-scope:
    - Push sending logic (see push/service.py)
    - Subscription persistence (see push/repo.py)
"""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException

from .. import db
from ..push import repo as push_repo
from ..routes.loops._common import SettingsDep
from ..schemas.push import (
    PushSubscribeResponse,
    PushSubscriptionIn,
    VapidPublicKeyResponse,
)

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/vapid_public_key", response_model=VapidPublicKeyResponse)
def vapid_public_key(settings: SettingsDep) -> VapidPublicKeyResponse:
    """Return the VAPID public key for client push subscription.

    Raises:
        404: If push is not configured (no VAPID keys)
    """
    if not settings.push_vapid_public_key:
        raise HTTPException(status_code=404, detail="push_not_configured")
    return VapidPublicKeyResponse(public_key=settings.push_vapid_public_key)


@router.post("/subscribe", response_model=PushSubscribeResponse)
def subscribe(
    subscription: PushSubscriptionIn,
    settings: SettingsDep,
    user_agent: Annotated[str | None, Header()] = None,
) -> PushSubscribeResponse:
    """Store or update a push subscription from the browser.

    Args:
        subscription: Push subscription details from PushManager.subscribe()
        settings: Application settings
        user_agent: Optional User-Agent header

    Returns:
        PushSubscribeResponse with ok=True on success
    """
    with db.core_connection(settings) as conn:
        push_repo.upsert_subscription(
            endpoint=subscription.endpoint,
            p256dh=subscription.keys.p256dh,
            auth=subscription.keys.auth,
            user_agent=user_agent,
            conn=conn,
        )
    return PushSubscribeResponse(ok=True)
