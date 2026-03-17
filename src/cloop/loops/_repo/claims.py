"""Loop-claim repository operations.

Purpose:
    Persist exclusive loop claims and lease lifecycle state.

Responsibilities:
    - Acquire, renew, read, release, and purge loop claims
    - Shape claim models returned to services and transports
    - Log repository-level claim lifecycle events

Non-scope:
    - Claim business rules above storage semantics
    - Core loop CRUD or dependency persistence
    - Review-session or planning persistence
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
from datetime import datetime

from ..models import LoopClaim, LoopClaimSummary, format_utc_datetime, parse_utc_datetime, utc_now

logger = logging.getLogger(__name__)


def claim_loop(
    *,
    loop_id: int,
    owner: str,
    lease_until: datetime,
    conn: sqlite3.Connection,
    token_bytes: int = 32,
) -> LoopClaim:
    """Acquire a claim on a loop. Returns claim with token.

    Args:
        loop_id: Loop to claim
        owner: Identifier for the claiming agent/client
        lease_until: When the claim expires
        conn: Database connection
        token_bytes: Number of bytes for token generation (default 32)

    Returns:
        LoopClaim with claim_token for subsequent operations

    Raises:
        sqlite3.IntegrityError: If already claimed (loop_id is PK)
    """
    token = secrets.token_hex(token_bytes)  # token_hex(n) produces 2n hex characters
    leased_at = utc_now()
    conn.execute(
        """
        INSERT INTO loop_claims (loop_id, owner, claim_token, leased_at, lease_until)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            loop_id,
            owner,
            token,
            format_utc_datetime(leased_at),
            format_utc_datetime(lease_until),
        ),
    )
    logger.info(
        "Loop claimed: loop_id=%s owner=%s lease_until=%s",
        loop_id,
        owner,
        format_utc_datetime(lease_until),
    )
    return LoopClaim(
        loop_id=loop_id,
        owner=owner,
        claim_token=token,
        leased_at_utc=leased_at,
        lease_until_utc=lease_until,
    )


def read_claim(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
) -> LoopClaim | None:
    """Read the current claim for a loop, if any.

    Args:
        loop_id: Loop to check
        conn: Database connection

    Returns:
        LoopClaim if exists, None otherwise
    """
    row = conn.execute(
        """
        SELECT loop_id, owner, claim_token, leased_at, lease_until
        FROM loop_claims
        WHERE loop_id = ?
        """,
        (loop_id,),
    ).fetchone()
    if row is None:
        return None
    return LoopClaim(
        loop_id=row["loop_id"],
        owner=row["owner"],
        claim_token=row["claim_token"],
        leased_at_utc=parse_utc_datetime(row["leased_at"]),
        lease_until_utc=parse_utc_datetime(row["lease_until"]),
    )


def renew_claim(
    *,
    loop_id: int,
    claim_token: str,
    new_lease_until: datetime,
    conn: sqlite3.Connection,
) -> LoopClaim | None:
    """Extend a claim's lease. Returns updated claim or None if token invalid.

    Args:
        loop_id: Loop with existing claim
        claim_token: Token from original claim
        new_lease_until: New expiry time
        conn: Database connection

    Returns:
        Updated LoopClaim if successful, None if token invalid or expired
    """
    now_str = format_utc_datetime(utc_now())
    cursor = conn.execute(
        """
        UPDATE loop_claims
        SET lease_until = ?
        WHERE loop_id = ? AND claim_token = ? AND lease_until > ?
        """,
        (format_utc_datetime(new_lease_until), loop_id, claim_token, now_str),
    )
    if cursor.rowcount == 0:
        return None
    logger.info(
        "Claim renewed: loop_id=%s new_lease_until=%s",
        loop_id,
        format_utc_datetime(new_lease_until),
    )
    return read_claim(loop_id=loop_id, conn=conn)


def release_claim(
    *,
    loop_id: int,
    claim_token: str,
    conn: sqlite3.Connection,
) -> bool:
    """Release a claim. Returns True if released, False if not found.

    Args:
        loop_id: Loop to release
        claim_token: Token from original claim
        conn: Database connection

    Returns:
        True if claim was released, False if not found
    """
    cursor = conn.execute(
        """
        DELETE FROM loop_claims
        WHERE loop_id = ? AND claim_token = ?
        """,
        (loop_id, claim_token),
    )
    released = cursor.rowcount > 0
    if released:
        logger.info("Claim released: loop_id=%s", loop_id)
    return released


def release_claim_by_loop_id(
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
    cursor = conn.execute(
        "DELETE FROM loop_claims WHERE loop_id = ?",
        (loop_id,),
    )
    return cursor.rowcount > 0


def purge_expired_claims(
    *,
    conn: sqlite3.Connection,
) -> int:
    """Delete all expired claims. Returns count purged.

    Args:
        conn: Database connection

    Returns:
        Number of expired claims deleted
    """
    now_str = format_utc_datetime(utc_now())
    cursor = conn.execute(
        "DELETE FROM loop_claims WHERE lease_until <= ?",
        (now_str,),
    )
    purged_count = cursor.rowcount
    if purged_count > 0:
        logger.info("Purged expired claims: count=%s", purged_count)
    return purged_count


def list_active_claims(
    *,
    owner: str | None = None,
    limit: int = 100,
    conn: sqlite3.Connection,
) -> list[LoopClaimSummary]:
    """List all active (non-expired) claims, optionally filtered by owner.

    Args:
        owner: Optional owner filter
        limit: Max results
        conn: Database connection

    Returns:
        List of active LoopClaimSummaries (without tokens) ordered by lease_until ascending
    """
    now_str = format_utc_datetime(utc_now())
    if owner:
        rows = conn.execute(
            """
            SELECT loop_id, owner, leased_at, lease_until
            FROM loop_claims
            WHERE owner = ? AND lease_until > ?
            ORDER BY lease_until ASC
            LIMIT ?
            """,
            (owner, now_str, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT loop_id, owner, leased_at, lease_until
            FROM loop_claims
            WHERE lease_until > ?
            ORDER BY lease_until ASC
            LIMIT ?
            """,
            (now_str, limit),
        ).fetchall()
    return [
        LoopClaimSummary(
            loop_id=r["loop_id"],
            owner=r["owner"],
            leased_at_utc=parse_utc_datetime(r["leased_at"]),
            lease_until_utc=parse_utc_datetime(r["lease_until"]),
        )
        for r in rows
    ]
