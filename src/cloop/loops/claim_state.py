"""Shared helpers for active-claim behavior.

Purpose:
    Keep claim expiry, serialization, and mutation-gate validation consistent
    across services that read or enforce loop claims.

Responsibilities:
    - Resolve whether a stored claim is still active
    - Serialize claim records for external responses
    - Validate claim tokens for write operations

Non-scope:
    - Does not create, renew, or release claims
    - Does not own claim persistence primitives
    - Does not emit claim lifecycle events
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import repo
from .errors import ClaimNotFoundError, LoopClaimedError
from .models import LoopClaim, LoopClaimSummary, format_utc_datetime, utc_now


def read_active_claim(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> LoopClaim | None:
    """Return the active claim for a loop, ignoring expired leases."""
    claim = repo.read_claim(loop_id=loop_id, conn=conn)
    if claim is None or claim.lease_until_utc <= utc_now():
        return None
    return claim


def claim_to_dict(claim: LoopClaim | LoopClaimSummary) -> dict[str, Any]:
    """Serialize a claim without exposing its token."""
    return {
        "loop_id": claim.loop_id,
        "owner": claim.owner,
        "leased_at_utc": format_utc_datetime(claim.leased_at_utc),
        "lease_until_utc": format_utc_datetime(claim.lease_until_utc),
    }


def validate_claim_for_update(
    *,
    loop_id: int,
    claim_token: str | None,
    conn: sqlite3.Connection,
) -> None:
    """Ensure the caller may mutate the loop under the current claim state."""
    claim = read_active_claim(loop_id=loop_id, conn=conn)
    if claim is None:
        return

    if claim_token is None:
        raise LoopClaimedError(
            loop_id=loop_id,
            owner=claim.owner,
            lease_until=format_utc_datetime(claim.lease_until_utc),
        )

    if claim.claim_token != claim_token:
        raise ClaimNotFoundError(loop_id)
