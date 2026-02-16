"""Loop webhook subscription endpoints.

Purpose:
    HTTP endpoints for managing webhook subscriptions.

Endpoints:
- POST /webhooks/subscriptions: Create a webhook subscription
- GET /webhooks/subscriptions: List all webhook subscriptions
- PATCH /webhooks/subscriptions/{subscription_id}: Update a subscription
- DELETE /webhooks/subscriptions/{subscription_id}: Delete a subscription
- GET /webhooks/subscriptions/{subscription_id}/deliveries: List deliveries
"""

import secrets
from typing import Annotated, List

from fastapi import APIRouter, HTTPException, Query

from ... import db
from ...schemas.loops import (
    WebhookDeliveryResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreateResponse,
    WebhookSubscriptionResponse,
    WebhookSubscriptionUpdate,
)
from ...webhooks import repo as webhooks_repo
from ._common import SettingsDep

router = APIRouter()


def _generate_webhook_secret() -> str:
    """Generate a secure random webhook secret.

    Returns:
        A URL-safe base64-encoded secret string.
    """
    return secrets.token_urlsafe(32)


@router.post("/webhooks/subscriptions", response_model=WebhookSubscriptionCreateResponse)
def create_webhook_subscription(
    request: WebhookSubscriptionCreate,
    settings: SettingsDep,
) -> WebhookSubscriptionCreateResponse:
    """Create a new webhook subscription.

    The secret returned in the response is the ONLY time it will be
    provided. Store it securely to verify webhook signatures.
    """
    secret = _generate_webhook_secret()
    with db.core_connection(settings) as conn:
        subscription = webhooks_repo.create_subscription(
            url=request.url,
            secret=secret,
            event_types=request.event_types,
            description=request.description,
            conn=conn,
        )
    return WebhookSubscriptionCreateResponse(
        id=subscription.id,
        url=subscription.url,
        event_types=subscription.event_types,
        active=subscription.active,
        description=subscription.description,
        created_at_utc=subscription.created_at,
        updated_at_utc=subscription.updated_at,
        secret=secret,
    )


@router.get("/webhooks/subscriptions", response_model=List[WebhookSubscriptionResponse])
def list_webhook_subscriptions(settings: SettingsDep) -> List[WebhookSubscriptionResponse]:
    """List all webhook subscriptions."""
    with db.core_connection(settings) as conn:
        subscriptions = webhooks_repo.list_subscriptions(conn=conn)
    return [
        WebhookSubscriptionResponse(
            id=sub.id,
            url=sub.url,
            event_types=sub.event_types,
            active=sub.active,
            description=sub.description,
            created_at_utc=sub.created_at,
            updated_at_utc=sub.updated_at,
        )
        for sub in subscriptions
    ]


@router.patch(
    "/webhooks/subscriptions/{subscription_id}", response_model=WebhookSubscriptionResponse
)
def update_webhook_subscription(
    subscription_id: int,
    request: WebhookSubscriptionUpdate,
    settings: SettingsDep,
) -> WebhookSubscriptionResponse:
    """Update a webhook subscription."""
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    with db.core_connection(settings) as conn:
        subscription = webhooks_repo.update_subscription(
            subscription_id=subscription_id,
            url=fields.get("url"),
            event_types=fields.get("event_types"),
            active=fields.get("active"),
            description=fields.get("description"),
            conn=conn,
        )
        if subscription is None:
            raise HTTPException(status_code=404, detail="subscription_not_found")

    return WebhookSubscriptionResponse(
        id=subscription.id,
        url=subscription.url,
        event_types=subscription.event_types,
        active=subscription.active,
        description=subscription.description,
        created_at_utc=subscription.created_at,
        updated_at_utc=subscription.updated_at,
    )


@router.delete("/webhooks/subscriptions/{subscription_id}")
def delete_webhook_subscription(
    subscription_id: int,
    settings: SettingsDep,
) -> dict[str, bool]:
    """Delete a webhook subscription."""
    with db.core_connection(settings) as conn:
        deleted = webhooks_repo.delete_subscription(
            subscription_id=subscription_id,
            conn=conn,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="subscription_not_found")
    return {"deleted": True}


@router.get(
    "/webhooks/subscriptions/{subscription_id}/deliveries",
    response_model=List[WebhookDeliveryResponse],
)
def list_webhook_deliveries(
    subscription_id: int,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> List[WebhookDeliveryResponse]:
    """List recent deliveries for a webhook subscription."""
    with db.core_connection(settings) as conn:
        # Verify subscription exists
        subscription = webhooks_repo.get_subscription(
            subscription_id=subscription_id,
            conn=conn,
        )
        if subscription is None:
            raise HTTPException(status_code=404, detail="subscription_not_found")

        deliveries = webhooks_repo.list_deliveries_for_subscription(
            subscription_id=subscription_id,
            conn=conn,
            limit=limit,
        )

    return [
        WebhookDeliveryResponse(
            id=d.id,
            subscription_id=d.subscription_id,
            event_id=d.event_id,
            event_type=d.event_type,
            status=d.status.value,
            http_status=d.http_status,
            error_message=d.error_message,
            attempt_count=d.attempt_count,
            next_retry_at=d.next_retry_at,
            created_at_utc=d.created_at,
            updated_at_utc=d.updated_at,
        )
        for d in deliveries
    ]
