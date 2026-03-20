"""CLI command dispatch tree for parsed `cloop` arguments.

Purpose:
    Route parsed argparse namespaces to the correct command handler without
    mixing parser construction into one oversized module.

Responsibilities:
    - Define the canonical command-to-handler dispatch tree
    - Centralize nested subcommand routing and unknown-command failures
    - Keep `cloop.cli_package.main` focused on orchestration

Scope:
    - Parsed-argument dispatch only
    - Command tree structure and parser-facing unknown-command errors

Non-scope:
    - Parser construction
    - Database initialization
    - Command handler business logic

Usage:
    - Call `dispatch_command(parser=..., args=..., settings=...)` after
      argparse parsing and database initialization are complete.

Invariants/Assumptions:
    - Every dispatch leaf returns a process exit code.
    - Nested selectors (for example `loop_command` or `backup_command`) are set
      by the corresponding parser builders before dispatch runs.
    - Unknown command states are treated as parser errors and terminate with the
      standard argparse exit behavior.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import NoReturn

from ..settings import Settings
from .backup_commands import (
    backup_create_command,
    backup_list_command,
    backup_restore_command,
    backup_rotate_command,
    backup_verify_command,
)
from .chat_commands import chat_command
from .loop_bulk_commands import (
    loop_bulk_close_command,
    loop_bulk_enrich_command,
    loop_bulk_snooze_command,
    loop_bulk_update_command,
)
from .loop_claim_commands import (
    loop_claim_command,
    loop_force_release_claim_command,
    loop_get_claim_command,
    loop_list_claims_command,
    loop_release_claim_command,
    loop_renew_claim_command,
)
from .loop_core_commands import (
    capture_command,
    inbox_command,
    loop_close_command,
    loop_enrich_command,
    loop_get_command,
    loop_list_command,
    loop_search_command,
    loop_semantic_search_command,
    loop_snooze_command,
    loop_status_command,
    loop_update_command,
    next_command,
)
from .loop_dep_commands import loop_dep_command
from .loop_misc_commands import (
    clarification_answer_command,
    clarification_answer_many_command,
    clarification_list_command,
    clarification_refine_command,
    export_command,
    import_command,
    loop_events_command,
    loop_metrics_command,
    loop_review_command,
    loop_undo_command,
    projects_command,
    suggestion_apply_command,
    suggestion_list_command,
    suggestion_reject_command,
    suggestion_show_command,
    tags_command,
)
from .loop_relationship_commands import (
    loop_relationship_confirm_command,
    loop_relationship_dismiss_command,
    loop_relationship_queue_command,
    loop_relationship_review_command,
)
from .loop_timer_commands import sessions_command, timer_command
from .loop_view_commands import (
    loop_view_apply_command,
    loop_view_create_command,
    loop_view_delete_command,
    loop_view_get_command,
    loop_view_list_command,
    loop_view_update_command,
)
from .memory_commands import (
    memory_create_command,
    memory_delete_command,
    memory_get_command,
    memory_list_command,
    memory_search_command,
    memory_update_command,
)
from .planning_commands import (
    planning_session_create_command,
    planning_session_delete_command,
    planning_session_execute_command,
    planning_session_get_command,
    planning_session_list_command,
    planning_session_move_command,
    planning_session_refresh_command,
    planning_session_rollback_command,
)
from .rag_commands import ask_command, ingest_command
from .review_commands import (
    enrichment_review_action_create_command,
    enrichment_review_action_delete_command,
    enrichment_review_action_get_command,
    enrichment_review_action_list_command,
    enrichment_review_action_update_command,
    enrichment_review_session_answer_clarifications_command,
    enrichment_review_session_apply_action_command,
    enrichment_review_session_create_command,
    enrichment_review_session_delete_command,
    enrichment_review_session_get_command,
    enrichment_review_session_list_command,
    enrichment_review_session_move_command,
    enrichment_review_session_update_command,
    relationship_review_action_create_command,
    relationship_review_action_delete_command,
    relationship_review_action_get_command,
    relationship_review_action_list_command,
    relationship_review_action_update_command,
    relationship_review_session_apply_action_command,
    relationship_review_session_create_command,
    relationship_review_session_delete_command,
    relationship_review_session_get_command,
    relationship_review_session_list_command,
    relationship_review_session_move_command,
    relationship_review_session_update_command,
)
from .template_commands import (
    template_create_command,
    template_delete_command,
    template_from_loop_command,
    template_list_command,
    template_show_command,
)
from .working_set_commands import working_set_undo_command

CommandHandler = Callable[[argparse.Namespace, Settings], int]


@dataclass(frozen=True, slots=True)
class DispatchBranch:
    """One nested dispatch selector inside the CLI command tree."""

    selector: str
    error_label: str
    targets: Mapping[str, "DispatchTarget"]


type DispatchTarget = CommandHandler | DispatchBranch


def _branch(
    selector: str,
    error_label: str,
    targets: Mapping[str, DispatchTarget],
) -> DispatchBranch:
    """Build one dispatch branch with a typed selector label."""
    return DispatchBranch(selector=selector, error_label=error_label, targets=targets)


LOOP_TARGET = _branch(
    "loop_command",
    "loop command",
    {
        "get": loop_get_command,
        "list": loop_list_command,
        "search": loop_search_command,
        "semantic-search": loop_semantic_search_command,
        "update": loop_update_command,
        "status": loop_status_command,
        "close": loop_close_command,
        "enrich": loop_enrich_command,
        "snooze": loop_snooze_command,
        "claim": loop_claim_command,
        "renew": loop_renew_claim_command,
        "release": loop_release_claim_command,
        "get-claim": loop_get_claim_command,
        "claims": loop_list_claims_command,
        "force-release": loop_force_release_claim_command,
        "dep": loop_dep_command,
        "timer": timer_command,
        "sessions": sessions_command,
        "review": loop_review_command,
        "events": loop_events_command,
        "undo": loop_undo_command,
        "metrics": loop_metrics_command,
        "relationship": _branch(
            "relationship_command",
            "relationship command",
            {
                "review": loop_relationship_review_command,
                "queue": loop_relationship_queue_command,
                "confirm": loop_relationship_confirm_command,
                "dismiss": loop_relationship_dismiss_command,
            },
        ),
        "view": _branch(
            "view_command",
            "view command",
            {
                "create": loop_view_create_command,
                "list": loop_view_list_command,
                "get": loop_view_get_command,
                "update": loop_view_update_command,
                "delete": loop_view_delete_command,
                "apply": loop_view_apply_command,
            },
        ),
        "bulk": _branch(
            "bulk_action",
            "bulk action",
            {
                "update": loop_bulk_update_command,
                "close": loop_bulk_close_command,
                "snooze": loop_bulk_snooze_command,
                "enrich": loop_bulk_enrich_command,
            },
        ),
    },
)

REVIEW_TARGET = _branch(
    "review_command",
    "review command",
    {
        "relationship-action": _branch(
            "review_relationship_action_command",
            "relationship-action command",
            {
                "create": relationship_review_action_create_command,
                "list": relationship_review_action_list_command,
                "get": relationship_review_action_get_command,
                "update": relationship_review_action_update_command,
                "delete": relationship_review_action_delete_command,
            },
        ),
        "relationship-session": _branch(
            "review_relationship_session_command",
            "relationship-session command",
            {
                "create": relationship_review_session_create_command,
                "list": relationship_review_session_list_command,
                "get": relationship_review_session_get_command,
                "move": relationship_review_session_move_command,
                "update": relationship_review_session_update_command,
                "delete": relationship_review_session_delete_command,
                "apply-action": relationship_review_session_apply_action_command,
            },
        ),
        "enrichment-action": _branch(
            "review_enrichment_action_command",
            "enrichment-action command",
            {
                "create": enrichment_review_action_create_command,
                "list": enrichment_review_action_list_command,
                "get": enrichment_review_action_get_command,
                "update": enrichment_review_action_update_command,
                "delete": enrichment_review_action_delete_command,
            },
        ),
        "enrichment-session": _branch(
            "review_enrichment_session_command",
            "enrichment-session command",
            {
                "create": enrichment_review_session_create_command,
                "list": enrichment_review_session_list_command,
                "get": enrichment_review_session_get_command,
                "move": enrichment_review_session_move_command,
                "update": enrichment_review_session_update_command,
                "delete": enrichment_review_session_delete_command,
                "apply-action": enrichment_review_session_apply_action_command,
                "answer-clarifications": enrichment_review_session_answer_clarifications_command,
            },
        ),
    },
)

PLAN_TARGET = _branch(
    "plan_command",
    "plan command",
    {
        "session": _branch(
            "plan_session_command",
            "plan session command",
            {
                "create": planning_session_create_command,
                "list": planning_session_list_command,
                "get": planning_session_get_command,
                "move": planning_session_move_command,
                "refresh": planning_session_refresh_command,
                "execute": planning_session_execute_command,
                "rollback": planning_session_rollback_command,
                "delete": planning_session_delete_command,
            },
        )
    },
)

ROOT_TARGET = _branch(
    "command",
    "command",
    {
        "ingest": ingest_command,
        "ask": ask_command,
        "chat": chat_command,
        "capture": capture_command,
        "inbox": inbox_command,
        "next": next_command,
        "loop": LOOP_TARGET,
        "template": _branch(
            "template_command",
            "template command",
            {
                "list": template_list_command,
                "show": template_show_command,
                "create": template_create_command,
                "delete": template_delete_command,
                "from-loop": template_from_loop_command,
            },
        ),
        "tags": tags_command,
        "projects": projects_command,
        "export": export_command,
        "import": import_command,
        "backup": _branch(
            "backup_command",
            "backup command",
            {
                "create": backup_create_command,
                "restore": backup_restore_command,
                "list": backup_list_command,
                "verify": backup_verify_command,
                "rotate": backup_rotate_command,
            },
        ),
        "suggestion": _branch(
            "suggestion_cmd",
            "suggestion command",
            {
                "list": suggestion_list_command,
                "show": suggestion_show_command,
                "apply": suggestion_apply_command,
                "reject": suggestion_reject_command,
            },
        ),
        "clarification": _branch(
            "clarification_cmd",
            "clarification command",
            {
                "list": clarification_list_command,
                "answer": clarification_answer_command,
                "answer-many": clarification_answer_many_command,
                "refine": clarification_refine_command,
            },
        ),
        "review": REVIEW_TARGET,
        "plan": PLAN_TARGET,
        "memory": _branch(
            "memory_command",
            "memory command",
            {
                "list": memory_list_command,
                "search": memory_search_command,
                "get": memory_get_command,
                "create": memory_create_command,
                "update": memory_update_command,
                "delete": memory_delete_command,
            },
        ),
        "working-set": _branch(
            "working_set_command",
            "working-set command",
            {
                "undo": working_set_undo_command,
            },
        ),
    },
)


def dispatch_command(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    """Dispatch parsed CLI arguments to the registered command handler."""
    return _dispatch_target(parser=parser, args=args, settings=settings, target=ROOT_TARGET)


def _dispatch_target(
    *,
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    settings: Settings,
    target: DispatchTarget,
) -> int:
    """Resolve one dispatch target, recursing through nested subcommands."""
    if isinstance(target, DispatchBranch):
        command_name = getattr(args, target.selector, None)
        if not isinstance(command_name, str):
            _parser_error(parser, f"Missing {target.error_label}")
        next_target = target.targets.get(command_name)
        if next_target is None:
            _parser_error(parser, f"Unknown {target.error_label}: {command_name}")
        return _dispatch_target(parser=parser, args=args, settings=settings, target=next_target)
    return target(args, settings)


def _parser_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    """Terminate with the standard argparse parser error contract."""
    parser.error(message)
    raise AssertionError("argparse.ArgumentParser.error() should not return")
