"""Template command handlers.

Purpose:
    Implement CLI command handlers for template operations.

Responsibilities:
    - Handle template list, show, create, delete, from-loop commands
    - Call template service layer
    - Format output
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from typing import Any

from .. import db
from ..loops import repo
from ..loops.errors import LoopNotFoundError, ValidationError
from ..loops.service import create_template_from_loop
from ..loops.utils import normalize_tags
from ..settings import Settings
from .output import emit_output


def template_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template list' command."""
    with db.core_connection(settings) as conn:
        templates = repo.list_loop_templates(conn=conn)

    payload = [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "is_system": bool(t["is_system"]),
        }
        for t in templates
    ]
    emit_output(payload, args.format)
    return 0


def template_show_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template show' command."""
    with db.core_connection(settings) as conn:
        # Try as ID first
        try:
            template_id = int(args.name_or_id)
            template = repo.get_loop_template(template_id=template_id, conn=conn)
        except ValueError:
            template = repo.get_loop_template_by_name(name=args.name_or_id, conn=conn)

    if not template:
        print(f"Template not found: {args.name_or_id}", file=sys.stderr)
        return 2

    defaults = json.loads(template["defaults_json"]) if template["defaults_json"] else {}
    payload = {
        "id": template["id"],
        "name": template["name"],
        "description": template["description"],
        "pattern": template["raw_text_pattern"],
        "defaults": defaults,
        "is_system": bool(template["is_system"]),
    }
    emit_output(payload, args.format)
    return 0


def template_create_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template create' command."""
    defaults: dict[str, Any] = {}
    if args.tags:
        defaults["tags"] = normalize_tags(args.tags.split(","))
    if args.time:
        defaults["time_minutes"] = args.time
    if args.actionable:
        defaults["actionable"] = True

    with db.core_connection(settings) as conn:
        try:
            template = repo.create_loop_template(
                name=args.name,
                description=args.description,
                raw_text_pattern=args.pattern,
                defaults_json=defaults,
                is_system=False,
                conn=conn,
            )
        except ValidationError as e:
            print(f"Error: {e.message}", file=sys.stderr)
            return 1

    emit_output({"id": template["id"], "name": template["name"]}, args.format)
    return 0


def template_delete_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template delete' command."""
    with db.core_connection(settings) as conn:
        try:
            template_id = int(args.name_or_id)
            template = repo.get_loop_template(template_id=template_id, conn=conn)
        except ValueError:
            template = repo.get_loop_template_by_name(name=args.name_or_id, conn=conn)

        if not template:
            print(f"Template not found: {args.name_or_id}", file=sys.stderr)
            return 2

        try:
            deleted = repo.delete_loop_template(template_id=template["id"], conn=conn)
        except ValidationError as e:
            print(f"Cannot delete: {e.message}", file=sys.stderr)
            return 1

    if deleted:
        print(f"Deleted template: {template['name']}")
        return 0
    return 1


def template_from_loop_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop template from-loop' command."""
    with db.core_connection(settings) as conn:
        try:
            template = create_template_from_loop(
                loop_id=args.loop_id,
                template_name=args.name,
                conn=conn,
            )
        except LoopNotFoundError:
            print(f"Loop not found: {args.loop_id}", file=sys.stderr)
            return 2
        except ValidationError as e:
            print(f"Error: {e.message}", file=sys.stderr)
            return 1

    emit_output({"id": template["id"], "name": template["name"]}, args.format)
    return 0
