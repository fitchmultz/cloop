"""Push notification subscription endpoints.

Purpose:
    Manage browser push subscriptions for scheduler event delivery.

Responsibilities:
    - Register new push subscriptions with unique endpoint constraint
    - Update existing subscriptions on re-subscription
    - Remove subscriptions on request
    - Validate subscription payload

Non-scope:
    - Push sending (see push_sender.py)
    - Service worker handling (client-side)

Endpoints:
    POST /loops/push/subscribe - Register a push subscription
    DELETE /loops/push/subscribe - Remove a push subscription
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ... import db
from ._common import SettingsDep

router = APIRouter()


class PushSubscriptionRequest(BaseModel):
    """Push subscription data from browser."""

    endpoint: str = Field(..., min_length=1, max_length=2000)
    keys: dict[str, str] = Field(..., description="Contains p256dh and auth keys")


class PushSubscriptionResponse(BaseModel):
    """Response for push subscription operations."""

    success: bool
    message: str


@router.post("/push/subscribe", response_model=PushSubscriptionResponse)
def subscribe_push(
    request: PushSubscriptionRequest,
    settings: SettingsDep,
) -> PushSubscriptionResponse:
    """Register a browser push subscription."""
    endpoint = request.endpoint
    p256dh = request.keys.get("p256dh")
    auth = request.keys.get("auth")

    if not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Missing p256dh or auth keys")

    with db.core_connection(settings) as conn:
        try:
            conn.execute(
                """INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(endpoint) DO UPDATE SET
                       p256dh = excluded.p256dh,
                       auth = excluded.auth,
                       updated_at_utc = datetime('now')
                """,
                (endpoint, p256dh, auth, None),
            )
            conn.commit()
        except sqlite3.Error as e:
            raise HTTPException(status_code=500, detail=f"Database error: {e}") from e

    return PushSubscriptionResponse(success=True, message="Subscription saved")


@router.delete("/push/subscribe", response_model=PushSubscriptionResponse)
def unsubscribe_push(
    endpoint: Annotated[str, Query(...)],
    settings: SettingsDep,
) -> PushSubscriptionResponse:
    """Remove a browser push subscription."""
    with db.core_connection(settings) as conn:
        cursor = conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        )
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Subscription not found")

    return PushSubscriptionResponse(success=True, message="Subscription removed")
