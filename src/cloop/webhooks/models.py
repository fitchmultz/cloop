"""Webhook domain models."""

from dataclasses import dataclass
from enum import StrEnum


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True, slots=True)
class WebhookSubscription:
    id: int
    url: str
    secret: str
    event_types: list[str]  # ["*"] means all
    active: bool
    description: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WebhookDelivery:
    id: int
    subscription_id: int
    event_id: int
    event_type: str
    payload_json: str
    status: DeliveryStatus
    http_status: int | None
    response_body: str | None
    error_message: str | None
    signature: str
    attempt_count: int
    next_retry_at: str | None
    created_at: str
    updated_at: str
