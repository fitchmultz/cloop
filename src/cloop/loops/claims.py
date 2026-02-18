"""Claim management service for exclusive loop access.

Purpose:
    Validate and enforce exclusive access claims on loops for multi-agent coordination.

Responsibilities:
    - Validate and enforce exclusive access claims on loops
    - Manage claim lifecycle: claim, renew, release, force-release
    - Track claim status and list active claims
    - Generate claim events for webhook delivery

Non-scope:
    - Not responsible for loop CRUD operations
    - Not responsible for claim repository implementation (see .repo)
    - Not responsible for webhook delivery (delegates to webhooks.service)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from typing import Any

from .. import typingx
from ..settings import Settings, get_settings
from ..webhooks.service import queue_deliveries
from . import repo
from .errors import ClaimNotFoundError, LoopClaimedError, LoopNotFoundError
from .models import LoopEventType, format_utc_datetime, utc_now

logger = logging.getLogger(__name__)


def _validate_claim_for_update(
    *,
    loop_id: int,
    claim_token: str | None,
    conn: sqlite3.Connection,
) -> None:
    """Validate that the caller has a valid claim on the loop.

    Call this at the start of mutation operations (update_loop, transition_status, etc.)

    Args:
        loop_id: Loop being modified
        claim_token: Token provided by caller (or None)
        conn: Database connection

    Raises:
        LoopClaimedError: If loop is claimed by someone else
        ClaimNotFoundError: If loop is claimed but no/invalid token provided
    """
    claim = repo.read_claim(loop_id=loop_id, conn=conn)
    if claim is None:
        return  # No claim, proceed

    # Check if claim has expired (don't purge, just check)
    if claim.lease_until_utc <= utc_now():
        return  # Claim expired, proceed

    if claim_token is None:
        raise LoopClaimedError(
            loop_id=loop_id,
            owner=claim.owner,
            lease_until=format_utc_datetime(claim.lease_until_utc),
        )

    if claim.claim_token != claim_token:
        raise ClaimNotFoundError(loop_id)


@typingx.validate_io()
def claim_loop(
    *,
    loop_id: int,
    owner: str,
    ttl_seconds: int | None = None,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Claim a loop for exclusive access.

    Args:
        loop_id: Loop to claim
        owner: Identifier for the claiming agent/client
        ttl_seconds: Lease duration (defaults to claim_default_ttl_seconds)
        conn: Database connection
        settings: Optional settings override

    Returns:
        Dict with claim details including claim_token for subsequent operations

    Raises:
        LoopNotFoundError: If loop doesn't exist
        LoopClaimedError: If loop is already claimed
    """
    settings = settings or get_settings()
    ttl = ttl_seconds or settings.claim_default_ttl_seconds
    ttl = min(ttl, settings.claim_max_ttl_seconds)

    # Verify loop exists
    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)

    # Purge expired claims first
    repo.purge_expired_claims(conn=conn)

    now = utc_now()
    lease_until = now + timedelta(seconds=ttl)

    # Retry loop handles race condition where claim expires between purge and insert
    # Max 3 attempts to prevent theoretical infinite retry on pathological timing
    for attempt in range(3):
        try:
            claim = repo.claim_loop(
                loop_id=loop_id,
                owner=owner,
                lease_until=lease_until,
                conn=conn,
                token_bytes=settings.claim_token_bytes,
            )
            break
        except sqlite3.IntegrityError:
            # Already claimed - get existing claim info
            existing = repo.read_claim(loop_id=loop_id, conn=conn)
            if existing and existing.lease_until_utc > now:
                raise LoopClaimedError(
                    loop_id=loop_id,
                    owner=existing.owner,
                    lease_until=format_utc_datetime(existing.lease_until_utc),
                ) from None
            # Race condition: claim expired between purge and insert
            if attempt < 2:  # Only purge and retry if not last attempt
                repo.purge_expired_claims(conn=conn)
            else:
                # Final attempt also failed - should be extremely rare
                raise RuntimeError(
                    f"Failed to acquire claim on loop {loop_id} after 3 attempts"
                ) from None

    # Record claim event
    event_payload = {
        "owner": owner,
        "lease_until": format_utc_datetime(lease_until),
    }
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.CLAIM.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.CLAIM.value,
        payload=event_payload,
        conn=conn,
    )

    logger.info(
        "Loop claimed successfully: loop_id=%s owner=%s ttl=%s lease_until=%s",
        loop_id,
        owner,
        ttl,
        format_utc_datetime(lease_until),
    )

    return {
        "loop_id": claim.loop_id,
        "owner": claim.owner,
        "claim_token": claim.claim_token,
        "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
        "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
    }


@typingx.validate_io()
def renew_claim(
    *,
    loop_id: int,
    claim_token: str,
    ttl_seconds: int | None = None,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Renew an existing claim.

    Args:
        loop_id: Loop with existing claim
        claim_token: Token from original claim
        ttl_seconds: New lease duration from now
        conn: Database connection
        settings: Optional settings override

    Returns:
        Dict with updated claim details

    Raises:
        ClaimNotFoundError: If token invalid or claim expired
    """
    settings = settings or get_settings()
    ttl = ttl_seconds or settings.claim_default_ttl_seconds
    ttl = min(ttl, settings.claim_max_ttl_seconds)

    now = utc_now()
    new_lease_until = now + timedelta(seconds=ttl)

    claim = repo.renew_claim(
        loop_id=loop_id,
        claim_token=claim_token,
        new_lease_until=new_lease_until,
        conn=conn,
    )
    if claim is None:
        raise ClaimNotFoundError(loop_id)

    logger.info(
        "Claim renewed successfully: loop_id=%s new_lease_until=%s",
        loop_id,
        format_utc_datetime(new_lease_until),
    )

    return {
        "loop_id": claim.loop_id,
        "owner": claim.owner,
        "claim_token": claim.claim_token,
        "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
        "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
    }


@typingx.validate_io()
def release_claim(
    *,
    loop_id: int,
    claim_token: str,
    conn: sqlite3.Connection,
) -> bool:
    """Release a claim on a loop.

    Args:
        loop_id: Loop to release
        claim_token: Token from original claim
        conn: Database connection

    Returns:
        True if released

    Raises:
        ClaimNotFoundError: If token doesn't match any active claim
    """
    released = repo.release_claim(loop_id=loop_id, claim_token=claim_token, conn=conn)
    if not released:
        raise ClaimNotFoundError(loop_id)

    event_payload = {"release_type": "explicit"}
    event_id = repo.insert_loop_event(
        loop_id=loop_id,
        event_type=LoopEventType.CLAIM_RELEASED.value,
        payload=event_payload,
        conn=conn,
    )
    queue_deliveries(
        event_id=event_id,
        event_type=LoopEventType.CLAIM_RELEASED.value,
        payload=event_payload,
        conn=conn,
    )

    logger.info("Claim released successfully: loop_id=%s", loop_id)

    return True


@typingx.validate_io()
def force_release_claim(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> bool:
    """Force-release any claim on a loop (admin override).

    Args:
        loop_id: Loop to release
        conn: Database connection

    Returns:
        True if a claim was released, False if no claim existed
    """
    claim = repo.read_claim(loop_id=loop_id, conn=conn)
    released = repo.release_claim_by_loop_id(loop_id=loop_id, conn=conn)
    if released and claim:
        logger.info(
            "Claim force-released: loop_id=%s original_owner=%s",
            loop_id,
            claim.owner,
        )
        event_payload = {
            "release_type": "forced",
            "original_owner": claim.owner,
        }
        event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type=LoopEventType.CLAIM_RELEASED.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.CLAIM_RELEASED.value,
            payload=event_payload,
            conn=conn,
        )
    return released


@typingx.validate_io()
def get_claim_status(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Get the current claim status for a loop.

    Args:
        loop_id: Loop to check
        conn: Database connection

    Returns:
        Dict with claim info (without token) or None if not claimed
    """
    # Purge expired claims first
    repo.purge_expired_claims(conn=conn)

    claim = repo.read_claim(loop_id=loop_id, conn=conn)
    if claim is None:
        return None
    # Don't expose the token in GET response
    return {
        "loop_id": claim.loop_id,
        "owner": claim.owner,
        "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
        "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
    }


@typingx.validate_io()
def list_active_claims(
    *,
    owner: str | None = None,
    limit: int = 100,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List all active (non-expired) claims, optionally filtered by owner.

    Args:
        owner: Optional owner filter
        limit: Max results
        conn: Database connection

    Returns:
        List of claim dicts (without tokens) ordered by lease_until ascending
    """
    # Purge expired claims first
    repo.purge_expired_claims(conn=conn)

    claims = repo.list_active_claims(owner=owner, limit=limit, conn=conn)
    # Don't expose tokens in list response
    return [
        {
            "loop_id": claim.loop_id,
            "owner": claim.owner,
            "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
            "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
        }
        for claim in claims
    ]
