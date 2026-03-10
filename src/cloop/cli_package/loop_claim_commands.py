"""Loop claim command handlers.

Purpose:
    Implement CLI command handlers for loop claim operations.

Responsibilities:
    - Handle claim, renew, release, get-claim, claims, and force-release commands
    - Delegate connection/error/output orchestration to the shared CLI runtime

Non-scope:
    - Claim expiration logic (handled by the service layer)
    - Claim persistence (handled by the repository/service layers)
    - Loop CRUD operations (handled in separate command modules)
"""

from __future__ import annotations

from argparse import Namespace

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
from ._runtime import cli_error, error_handler, run_cli_db_action


def loop_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop claim' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: claim_loop(
            loop_id=args.id,
            owner=args.owner,
            ttl_seconds=args.ttl,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopClaimedError,
                lambda exc: cli_error(str(exc)),
            ),
            error_handler(
                LoopNotFoundError,
                lambda exc: cli_error(f"loop {exc.loop_id} not found", exit_code=2),
            ),
        ],
    )


def loop_renew_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop renew' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: renew_claim(
            loop_id=args.id,
            claim_token=args.token,
            ttl_seconds=args.ttl,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=[
            error_handler(
                ClaimNotFoundError,
                lambda _exc: cli_error(f"no valid claim found for loop {args.id}"),
            )
        ],
    )


def loop_release_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop release' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: (
            release_claim(
                loop_id=args.id,
                claim_token=args.token,
                conn=conn,
            ),
            {"ok": True, "loop_id": args.id},
        )[1],
        output_format=args.format,
        error_handlers=[
            error_handler(
                ClaimNotFoundError,
                lambda _exc: cli_error(f"no valid claim found for loop {args.id}"),
            )
        ],
    )


def loop_get_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop get-claim' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: (
            get_claim_status(loop_id=args.id, conn=conn) or {"loop_id": args.id, "claimed": False}
        ),
        output_format=args.format,
    )


def loop_list_claims_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop claims' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: list_active_claims(
            owner=args.owner,
            limit=args.limit,
            conn=conn,
        ),
        output_format=args.format,
    )


def loop_force_release_claim_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop force-release' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: {
            "ok": True,
            "released": force_release_claim(loop_id=args.id, conn=conn),
            "loop_id": args.id,
        },
        output_format=args.format,
    )
