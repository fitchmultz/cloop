"""Template command handlers.

Purpose:
    Implement CLI command handlers for template operations.

Responsibilities:
    - Handle template list, show, create, delete, and from-loop commands
    - Normalize DB access, output emission, and expected-error mapping through
      the shared CLI runtime

Non-scope:
    - Loop lifecycle and state transitions
    - Template validation logic beyond CLI argument-to-payload shaping
    - Direct persistence details
"""

from __future__ import annotations

import json
from argparse import Namespace
from typing import Any

from ..loops import repo
from ..loops.errors import LoopNotFoundError, ValidationError
from ..loops.service import create_template_from_loop
from ..loops.utils import normalize_tags
from ..settings import Settings
from ._runtime import cli_error, error_handler, run_cli_db_action


def _resolve_template(conn: Any, name_or_id: str) -> dict[str, Any] | None:
    try:
        return repo.get_loop_template(template_id=int(name_or_id), conn=conn)
    except ValueError:
        return repo.get_loop_template_by_name(name=name_or_id, conn=conn)


def template_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template list' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: [
            {
                "id": template["id"],
                "name": template["name"],
                "description": template["description"],
                "is_system": bool(template["is_system"]),
            }
            for template in repo.list_loop_templates(conn=conn)
        ],
        output_format=args.format,
    )


def template_show_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template show' command."""

    def _action(conn: Any) -> dict[str, Any]:
        template = _resolve_template(conn, args.name_or_id)
        if not template:
            raise cli_error(f"template not found: {args.name_or_id}", exit_code=2)
        defaults = json.loads(template["defaults_json"]) if template["defaults_json"] else {}
        return {
            "id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "pattern": template["raw_text_pattern"],
            "defaults": defaults,
            "is_system": bool(template["is_system"]),
        }

    return run_cli_db_action(
        settings=settings,
        action=_action,
        output_format=args.format,
    )


def template_create_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template create' command."""
    defaults: dict[str, Any] = {}
    if args.tags:
        defaults["tags"] = normalize_tags(args.tags.split(","))
    if args.time:
        defaults["time_minutes"] = args.time
    if args.actionable:
        defaults["actionable"] = True

    return run_cli_db_action(
        settings=settings,
        action=lambda conn: {
            "id": repo.create_loop_template(
                name=args.name,
                description=args.description,
                raw_text_pattern=args.pattern,
                defaults_json=defaults,
                is_system=False,
                conn=conn,
            )["id"],
            "name": args.name,
        },
        output_format=args.format,
        error_handlers=[
            error_handler(
                ValidationError,
                lambda exc: cli_error(exc.message),
            )
        ],
    )


def template_delete_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template delete' command."""

    def _action(conn: Any) -> dict[str, Any]:
        template = _resolve_template(conn, args.name_or_id)
        if not template:
            raise cli_error(f"template not found: {args.name_or_id}", exit_code=2)
        repo.delete_loop_template(template_id=template["id"], conn=conn)
        return {"deleted": True, "id": template["id"], "name": template["name"]}

    return run_cli_db_action(
        settings=settings,
        action=_action,
        output_format=args.format,
        error_handlers=[
            error_handler(
                ValidationError,
                lambda exc: cli_error(exc.message),
            )
        ],
    )


def template_from_loop_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template from-loop' command."""
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: {
            "id": create_template_from_loop(
                loop_id=args.loop_id,
                template_name=args.name,
                conn=conn,
            )["id"],
            "name": args.name,
        },
        output_format=args.format,
        error_handlers=[
            error_handler(
                LoopNotFoundError,
                lambda exc: cli_error(f"loop {exc.loop_id} not found", exit_code=2),
            ),
            error_handler(
                ValidationError,
                lambda exc: cli_error(exc.message),
            ),
        ],
    )
