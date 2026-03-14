"""CLI handlers for duplicate/related-loop relationship review.

Purpose:
    Expose the shared relationship-review contract through the CLI.

Responsibilities:
    - Review duplicate/related candidates for one loop
    - List the relationship-review queue across loops
    - Confirm or dismiss one relationship candidate

Non-scope:
    - Merge preview and merge execution
    - Generic loop CRUD operations
"""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from ..loops import relationship_review
from ..settings import Settings
from ._runtime import run_cli_db_action
from .loop_core_commands import _emit_json, parse_list_status_filter
from .output import emit_output


def loop_relationship_review_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop loop relationship review`."""
    statuses = parse_list_status_filter(args.status)

    def _render(result: dict[str, Any]) -> None:
        if args.format == "json":
            _emit_json(result)
            return
        rows = [
            *result["duplicate_candidates"],
            *result["related_candidates"],
        ]
        emit_output(rows, args.format)

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: relationship_review.review_loop_relationships(
            loop_id=args.loop,
            statuses=statuses,
            duplicate_limit=args.duplicate_limit,
            related_limit=args.related_limit,
            conn=conn,
            settings=settings,
        ),
        render=_render,
    )


def loop_relationship_queue_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop loop relationship queue`."""
    statuses = parse_list_status_filter(args.status)

    def _render(result: dict[str, Any]) -> None:
        if args.format == "json":
            _emit_json(result)
            return
        rows = []
        for item in result["items"]:
            loop = item["loop"]
            rows.append(
                {
                    "loop_id": loop["id"],
                    "title": loop.get("title") or loop["raw_text"],
                    "status": loop["status"],
                    "duplicate_count": item["duplicate_count"],
                    "related_count": item["related_count"],
                    "top_score": item["top_score"],
                }
            )
        emit_output(rows, args.format)

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: relationship_review.list_relationship_review_queue(
            statuses=statuses,
            relationship_kind=args.kind,
            limit=args.limit,
            candidate_limit=args.candidate_limit,
            conn=conn,
            settings=settings,
        ),
        render=_render,
    )


def loop_relationship_confirm_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop loop relationship confirm`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: relationship_review.confirm_relationship(
            loop_id=args.loop,
            candidate_loop_id=args.candidate,
            relationship_type=args.type,
            conn=conn,
        ),
        output_format=args.format,
    )


def loop_relationship_dismiss_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop loop relationship dismiss`."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: relationship_review.dismiss_relationship(
            loop_id=args.loop,
            candidate_loop_id=args.candidate,
            relationship_type=args.type,
            conn=conn,
        ),
        output_format=args.format,
    )
