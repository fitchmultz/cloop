"""Webhook domain models.

Purpose:
    Define immutable models for webhook subscriptions, logical deliveries,
    and concrete HTTP delivery attempts.

Responsibilities:
    - Represent subscription configuration
    - Represent logical queued/in-flight/succeeded deliveries
    - Represent durable per-attempt HTTP execution records

Non-scope:
    - Database schema or queries
    - Network delivery logic
    - Signature generation or verification

Invariants/Assumptions:
    - `WebhookDelivery` is the logical delivery row, not the attempt log.
    - `WebhookDeliveryAttempt` stores exact request bytes and final attempt outcome.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_UTC_SUFFIX: Final[str] = "+00:00"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"
    PENDING = "queued"
    SUCCESS = "succeeded"
    FAILED = "dead_letter"


class DeliveryAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def epoch_to_iso(epoch: int | None) -> str | None:
    """Convert an epoch-second timestamp to an ISO UTC string."""
    if epoch is None:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace(_UTC_SUFFIX, "Z")


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
    source_payload_json: str
    last_attempt_payload_json: str | None
    status: DeliveryStatus
    http_status: int | None
    response_body: str | None
    error_message: str | None
    signature_header: str | None
    attempt_count: int
    active_attempt_number: int | None
    last_attempted_at: str | None
    next_retry_at_epoch: int | None
    lease_owner: str | None
    lease_until_epoch: int | None
    last_connect_ip: str | None
    created_at: str
    updated_at: str

    @property
    def next_retry_at(self) -> str | None:
        """Expose retry-at in ISO form for route serializers."""
        return epoch_to_iso(self.next_retry_at_epoch)

    @property
    def lease_until(self) -> str | None:
        """Expose in-flight lease expiry in ISO form."""
        return epoch_to_iso(self.lease_until_epoch)


@dataclass(frozen=True, slots=True)
class WebhookDeliveryAttempt:
    """Durable record for one HTTP attempt of a logical webhook delivery."""

    id: int
    delivery_id: int
    attempt_number: int
    status: DeliveryAttemptStatus
    started_at: str
    finished_at: str | None
    request_bytes: bytes | None
    signature_header: str | None
    http_status: int | None
    response_body: str | None
    error_message: str | None
    connect_ip: str | None
    created_at: str
