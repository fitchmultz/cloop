"""CLI handlers for saved review actions and review sessions.

Purpose:
    Execute `cloop review *` commands by delegating to the shared saved review
    workflow contract.

Responsibilities:
    - Parse CLI-only field formats such as comma-separated apply fields
    - Map review workflow domain errors to stable CLI exit codes
    - Delegate relationship/enrichment action and session operations to
      `loops/review_workflows.py`

Non-scope:
    - Review workflow business rules
    - Database lifecycle management outside the shared CLI runtime helper
    - Output formatting beyond choosing the requested renderer
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Sequence

from ..loops import enrichment_review, review_workflows
from ..loops.errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from ..settings import Settings
from ._runtime import cli_error, error_handler, fail_cli, run_cli_db_action


def _common_error_handlers() -> list:
    return [
        error_handler(ValidationError, lambda exc: cli_error(exc.message)),
        error_handler(ResourceNotFoundError, lambda exc: cli_error(exc.message, exit_code=2)),
        error_handler(LoopNotFoundError, lambda exc: cli_error(exc.message, exit_code=2)),
    ]


def _parse_fields(value: str | None) -> list[str] | None:
    if value is None:
        return None
    fields = [field.strip() for field in value.split(",") if field.strip()]
    return fields or None


def _parse_clarification_items(
    items: Sequence[str],
) -> list[enrichment_review.ClarificationAnswerInput]:
    parsed: list[enrichment_review.ClarificationAnswerInput] = []
    for item in items:
        clarification_text, separator, answer = item.partition("=")
        if not separator:
            fail_cli(f"invalid --item value '{item}' (expected <clarification_id>=<answer>)")
        try:
            clarification_id = int(clarification_text)
        except ValueError:
            fail_cli(f"invalid clarification id in --item value '{item}' (expected integer id)")
        if not answer.strip():
            fail_cli(f"invalid --item value '{item}' (answer must not be empty)")
        parsed.append(
            enrichment_review.ClarificationAnswerInput(
                clarification_id=clarification_id,
                answer=answer,
            )
        )
    return parsed


def relationship_review_action_create_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.create_relationship_review_action(
            name=args.name,
            action_type=args.action,
            relationship_type=args.relationship_type,
            description=args.description,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_action_list_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.list_relationship_review_actions(conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_action_get_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.get_relationship_review_action(
            action_preset_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_action_update_command(args: Namespace, settings: Settings) -> int:
    if all(
        value is None
        for value in (args.name, args.action, args.relationship_type, args.description)
    ):
        fail_cli("no fields to update")
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.update_relationship_review_action(
            action_preset_id=args.id,
            name=args.name,
            action_type=args.action,
            relationship_type=args.relationship_type,
            description=args.description,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_action_delete_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.delete_relationship_review_action(
            action_preset_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_session_create_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.create_relationship_review_session(
            name=args.name,
            query=args.query,
            relationship_kind=args.kind,
            candidate_limit=args.candidate_limit,
            item_limit=args.item_limit,
            current_loop_id=args.current_loop_id,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_session_list_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.list_relationship_review_sessions(conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_session_get_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.get_relationship_review_session(
            session_id=args.id,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_session_move_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.move_relationship_review_session(
            session_id=args.session,
            direction=args.direction,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_session_update_command(args: Namespace, settings: Settings) -> int:
    if not any(
        [
            args.name is not None,
            args.query is not None,
            args.kind is not None,
            args.candidate_limit is not None,
            args.item_limit is not None,
            args.current_loop_id is not None,
            args.clear_current_loop,
        ]
    ):
        fail_cli("no fields to update")
    current_loop_id = None if args.clear_current_loop else args.current_loop_id
    sentinel = (
        review_workflows._UNSET
        if not args.clear_current_loop and args.current_loop_id is None
        else current_loop_id
    )
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.update_relationship_review_session(
            session_id=args.id,
            name=args.name,
            query=args.query,
            relationship_kind=args.kind,
            candidate_limit=args.candidate_limit,
            item_limit=args.item_limit,
            current_loop_id=sentinel,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_session_delete_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.delete_relationship_review_session(
            session_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def relationship_review_session_apply_action_command(args: Namespace, settings: Settings) -> int:
    if args.action_id is None and (args.action is None or args.relationship_type is None):
        fail_cli("provide --action-id or both --action and --relationship-type")
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.execute_relationship_review_session_action(
            session_id=args.session,
            loop_id=args.loop,
            candidate_loop_id=args.candidate,
            candidate_relationship_type=args.candidate_type,
            action_preset_id=args.action_id,
            action_type=args.action,
            relationship_type=args.relationship_type,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_action_create_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.create_enrichment_review_action(
            name=args.name,
            action_type=args.action,
            fields=_parse_fields(args.fields),
            description=args.description,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_action_list_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.list_enrichment_review_actions(conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_action_get_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.get_enrichment_review_action(
            action_preset_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_action_update_command(args: Namespace, settings: Settings) -> int:
    if all(value is None for value in (args.name, args.action, args.fields, args.description)):
        fail_cli("no fields to update")
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.update_enrichment_review_action(
            action_preset_id=args.id,
            name=args.name,
            action_type=args.action,
            fields=_parse_fields(args.fields) if args.fields is not None else None,
            description=args.description,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_action_delete_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.delete_enrichment_review_action(
            action_preset_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_create_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.create_enrichment_review_session(
            name=args.name,
            query=args.query,
            pending_kind=args.pending_kind,
            suggestion_limit=args.suggestion_limit,
            clarification_limit=args.clarification_limit,
            item_limit=args.item_limit,
            current_loop_id=args.current_loop_id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_list_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.list_enrichment_review_sessions(conn=conn),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_get_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.get_enrichment_review_session(
            session_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_move_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.move_enrichment_review_session(
            session_id=args.session,
            direction=args.direction,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_update_command(args: Namespace, settings: Settings) -> int:
    if not any(
        [
            args.name is not None,
            args.query is not None,
            args.pending_kind is not None,
            args.suggestion_limit is not None,
            args.clarification_limit is not None,
            args.item_limit is not None,
            args.current_loop_id is not None,
            args.clear_current_loop,
        ]
    ):
        fail_cli("no fields to update")
    current_loop_id = None if args.clear_current_loop else args.current_loop_id
    sentinel = (
        review_workflows._UNSET
        if not args.clear_current_loop and args.current_loop_id is None
        else current_loop_id
    )
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.update_enrichment_review_session(
            session_id=args.id,
            name=args.name,
            query=args.query,
            pending_kind=args.pending_kind,
            suggestion_limit=args.suggestion_limit,
            clarification_limit=args.clarification_limit,
            item_limit=args.item_limit,
            current_loop_id=sentinel,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_delete_command(args: Namespace, settings: Settings) -> int:
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.delete_enrichment_review_session(
            session_id=args.id,
            conn=conn,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_apply_action_command(args: Namespace, settings: Settings) -> int:
    if args.action_id is None and args.action is None:
        fail_cli("provide --action-id or --action")
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.execute_enrichment_review_session_action(
            session_id=args.session,
            suggestion_id=args.suggestion,
            action_preset_id=args.action_id,
            action_type=args.action,
            fields=_parse_fields(args.fields),
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )


def enrichment_review_session_answer_clarifications_command(
    args: Namespace, settings: Settings
) -> int:
    answers = _parse_clarification_items(args.item)
    return run_cli_db_action(
        settings=settings,
        action=lambda conn: review_workflows.answer_enrichment_review_session_clarifications(
            session_id=args.session,
            loop_id=args.loop,
            answers=answers,
            conn=conn,
            settings=settings,
        ),
        output_format=args.format,
        error_handlers=_common_error_handlers(),
    )
