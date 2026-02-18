"""Loop view command handlers.

Purpose:
    Implement CLI command handlers for loop view operations.

Responsibilities:
    - Handle view create, list, get, update, delete, apply commands

Non-scope:
    - Does not handle loop data operations (see loop_core_commands.py)
    - Does not handle dependency operations (see loop_dep_commands.py)
    - Does not handle timer operations (see loop_timer_commands.py)
"""

from __future__ import annotations

import sys
from argparse import Namespace
from typing import Any, Dict

from .. import db
from ..loops.service import (
    apply_loop_view,
    create_loop_view,
    delete_loop_view,
    get_loop_view,
    list_loop_views,
    update_loop_view,
)
from ..settings import Settings
from .output import emit_output


def loop_view_create_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view create' command."""
    try:
        with db.core_connection(settings) as conn:
            view = create_loop_view(
                name=args.name,
                query=args.query,
                description=args.description,
                conn=conn,
            )
        emit_output(view, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_view_list_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view list' command."""
    with db.core_connection(settings) as conn:
        views = list_loop_views(conn=conn)
    emit_output(views, args.format)
    return 0


def loop_view_get_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view get' command."""
    try:
        with db.core_connection(settings) as conn:
            view = get_loop_view(view_id=args.id, conn=conn)
        emit_output(view, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_view_update_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view update' command."""
    fields: Dict[str, Any] = {}
    if args.name is not None:
        fields["name"] = args.name
    if args.query is not None:
        fields["query"] = args.query
    if args.description is not None:
        fields["description"] = args.description

    if not fields:
        print("error: no fields to update", file=sys.stderr)
        return 1

    try:
        with db.core_connection(settings) as conn:
            view = update_loop_view(view_id=args.id, conn=conn, **fields)
        emit_output(view, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_view_delete_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view delete' command."""
    try:
        with db.core_connection(settings) as conn:
            delete_loop_view(view_id=args.id, conn=conn)
        emit_output({"deleted": True}, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def loop_view_apply_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop view apply' command."""
    try:
        with db.core_connection(settings) as conn:
            result = apply_loop_view(
                view_id=args.id,
                limit=args.limit,
                offset=args.offset,
                conn=conn,
            )
        emit_output(result, args.format)
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
