"""Loop dependency command handlers.

Purpose:
    Implement CLI command handlers for loop dependency operations.

Responsibilities:
    - Handle dep add, remove, list, blocking commands
"""

from __future__ import annotations

import sys
from argparse import Namespace

from .. import db
from ..loops.errors import DependencyCycleError, LoopNotFoundError
from ..loops.service import (
    add_loop_dependency,
    get_loop_blocking,
    get_loop_dependencies,
    remove_loop_dependency,
)
from ..settings import Settings
from .output import emit_output


def loop_dep_command(args: Namespace, settings: Settings) -> int:
    """Handle 'cloop loop dep' commands."""
    action = args.dep_action
    try:
        with db.core_connection(settings) as conn:
            if action == "add":
                if not args.loop_id or not args.depends_on:
                    print("error: --loop and --on required for add", file=sys.stderr)
                    return 2
                try:
                    result = add_loop_dependency(
                        loop_id=args.loop_id,
                        depends_on_loop_id=args.depends_on,
                        conn=conn,
                    )
                    emit_output(result, args.format)
                    return 0
                except DependencyCycleError as e:
                    print(f"error: {e.message}", file=sys.stderr)
                    return 1

            elif action == "remove":
                if not args.loop_id or not args.depends_on:
                    print("error: --loop and --on required for remove", file=sys.stderr)
                    return 2
                result = remove_loop_dependency(
                    loop_id=args.loop_id,
                    depends_on_loop_id=args.depends_on,
                    conn=conn,
                )
                emit_output(result, args.format)
                return 0

            elif action == "list":
                if not args.loop_id:
                    print("error: --loop required for list", file=sys.stderr)
                    return 2
                deps = get_loop_dependencies(loop_id=args.loop_id, conn=conn)
                emit_output(deps, args.format)
                return 0

            elif action == "blocking":
                if not args.loop_id:
                    print("error: --loop required for blocking", file=sys.stderr)
                    return 2
                blocking = get_loop_blocking(loop_id=args.loop_id, conn=conn)
                emit_output(blocking, args.format)
                return 0

            else:
                print(f"error: unknown dep action: {action}", file=sys.stderr)
                return 2
    except LoopNotFoundError as e:
        print(f"error: loop not found: {e.loop_id}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
