"""Loop claim command handlers.

Purpose:
    Implement CLI command handlers for loop claim operations.

Responsibilities:
    - Handle claim, renew, release, get-claim, claims, force-release commands
"""

from __future__ import annotations

import sys
from argparse import Namespace

from .. import db
from ..loops.errors import ClaimNotFoundError, LoopClaimedError, LoopNotFoundError
from ..loops.service import (
    claim_loop,
    force_release_claim,
    get_claim_status,
    list_active_claims,
    release_claim,
    renew_claim,
)
from ..settings import Settings
from .output import emit_output


def loop_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop claim' command."""
    try:
        with db.core_connection(settings) as conn:
            result = claim_loop(
                loop_id=args.id,
                owner=args.owner,
                ttl_seconds=args.ttl,
                conn=conn,
                settings=settings,
            )
        emit_output(result, args.format)
        return 0
    except LoopClaimedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except LoopNotFoundError:
        print(f"error: loop {args.id} not found", file=sys.stderr)
        return 2


def loop_renew_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop renew' command."""
    try:
        with db.core_connection(settings) as conn:
            result = renew_claim(
                loop_id=args.id,
                claim_token=args.token,
                ttl_seconds=args.ttl,
                conn=conn,
                settings=settings,
            )
        emit_output(result, args.format)
        return 0
    except ClaimNotFoundError:
        print(f"error: no valid claim found for loop {args.id}", file=sys.stderr)
        return 1


def loop_release_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop release' command."""
    try:
        with db.core_connection(settings) as conn:
            release_claim(
                loop_id=args.id,
                claim_token=args.token,
                conn=conn,
            )
        emit_output({"ok": True, "loop_id": args.id}, args.format)
        return 0
    except ClaimNotFoundError:
        print(f"error: no valid claim found for loop {args.id}", file=sys.stderr)
        return 1


def loop_get_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop get-claim' command."""
    try:
        with db.core_connection(settings) as conn:
            result = get_claim_status(loop_id=args.id, conn=conn)
        if result is None:
            print(f"Loop {args.id} is not claimed", file=sys.stderr)
            return 0
        emit_output(result, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_list_claims_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop claims' command."""
    try:
        with db.core_connection(settings) as conn:
            result = list_active_claims(
                owner=args.owner,
                limit=args.limit,
                conn=conn,
            )
        emit_output(result, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_force_release_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop force-release' command."""
    try:
        with db.core_connection(settings) as conn:
            released = force_release_claim(loop_id=args.id, conn=conn)
        emit_output({"ok": True, "released": released, "loop_id": args.id}, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
