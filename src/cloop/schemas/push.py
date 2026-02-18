"""Pydantic schemas for web push notification endpoints.

Purpose:
    Define request/response models for push subscription and VAPID key APIs.

Responsibilities:
    - VapidPublicKeyResponse: Return public key for client subscription
    - PushSubscriptionIn: Receive subscription details from client
    - PushSubscribeResponse: Acknowledge subscription storage

Non-scope:
    - Push sending logic (see push/service.py)
    - Database operations (see push/repo.py)
"""

from pydantic import BaseModel, Field


class VapidPublicKeyResponse(BaseModel):
    """Response containing the VAPID public key for client push subscription."""

    public_key: str


class PushSubscriptionKeys(BaseModel):
    """Encryption keys for push subscription."""

    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    """Push subscription data from browser PushManager.subscribe()."""

    endpoint: str = Field(..., min_length=1)
    expirationTime: float | None = None
    keys: PushSubscriptionKeys


class PushSubscribeResponse(BaseModel):
    """Response acknowledging subscription storage."""

    ok: bool = True
