"""Shared HTTP registration for relationship and enrichment review workflows.

Purpose:
    Register the common review action/session route shapes once so idempotency
    paths, error mapping, and replay response handling stay aligned.

Responsibilities:
    - Attach shared CRUD/move/refresh/session-action routes on a caller router
    - Preserve legacy endpoint ``__name__`` values so OpenAPI operation metadata stays stable

Non-scope:
    - Relationship undo or enrichment clarification endpoints (stay in domain modules)

Scope:
    - Route registration helpers only
    - Callers supply domain-specific execute callables and response builders

Note:
    Avoid postponed evaluation of annotations here: endpoint bodies use closure-bound
    request/update model types and FastAPI must resolve those classes when building
    request validators.
"""

from dataclasses import dataclass
from types import GenericAlias
from typing import Any, Callable, cast

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .... import db
from ....loops import review_workflows
from ....loops.errors import LoopNotFoundError, ResourceNotFoundError, ValidationError
from ....schemas.loops import ReviewSessionMoveRequest
from ....settings import Settings
from .._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    map_not_found_to_404,
    map_validation_to_400,
    no_fields_to_update_http_exception,
    run_idempotent_loop_route,
)

LOOPS_PREFIX = "/loops"


def _idempotent_path(segment: str, suffix: str) -> str:
    return f"{LOOPS_PREFIX}/review/{segment}/{suffix}"


def _finish_mutation_or_replay(result: Any, *, build: Callable[[Any], Any] | None) -> Any:
    if isinstance(result, JSONResponse):
        return result
    if build is None:
        return result
    return build(result)


@dataclass(frozen=True)
class ReviewActionRouteHandles:
    list_actions: Callable[..., Any]
    create_action: Callable[..., Any]
    get_action: Callable[..., Any]
    update_action: Callable[..., Any]
    delete_action: Callable[..., Any]


def register_review_workflow_action_routes[
    AR: BaseModel,
    AC: BaseModel,
    AU: BaseModel,
](
    router: APIRouter,
    *,
    segment: str,
    action_response_model: type[AR],
    action_create_type: type[AC],
    action_update_type: type[AU],
    list_actions: Callable[[Any], list[Any]],
    build_action_response: Callable[[Any], Any],
    create_execute: Callable[[Any, AC], Any],
    get_action: Callable[[Any, int], Any],
    update_execute: Callable[[Any, int, dict[str, Any]], Any],
    delete_execute: Callable[[Any, int], Any],
) -> ReviewActionRouteHandles:
    """Register `/review/{segment}/actions*` CRUD and return endpoint callables."""

    def list_actions_endpoint(settings: SettingsDep) -> list[AR]:
        with db.core_connection(settings) as conn:
            rows = list_actions(conn)
        return [build_action_response(row) for row in rows]

    def create_action_endpoint(
        request: Any,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> AR | JSONResponse:
        payload = request.model_dump(mode="json")
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="POST",
                path=_idempotent_path(segment, "actions"),
                idempotency_key=idempotency_key,
                payload=payload,
                execute=lambda conn: create_execute(conn, request),
                response_status=201,
            )
        except ValidationError as exc:
            raise map_validation_to_400(exc) from None
        return _finish_mutation_or_replay(result, build=build_action_response)

    create_action_endpoint.__annotations__["request"] = action_create_type

    def get_action_endpoint(
        action_preset_id: int,
        settings: SettingsDep,
    ) -> AR:
        with db.core_connection(settings) as conn:
            try:
                action = get_action(conn, action_preset_id)
            except ResourceNotFoundError as exc:
                raise map_not_found_to_404(exc, resource_type="review action") from None
        return build_action_response(action)

    def update_action_endpoint(
        action_preset_id: int,
        request: Any,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> AR | JSONResponse:
        fields = request.model_dump(mode="json", exclude_unset=True)
        if not fields:
            raise no_fields_to_update_http_exception() from None
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="PATCH",
                path=_idempotent_path(segment, f"actions/{action_preset_id}"),
                idempotency_key=idempotency_key,
                payload={"action_preset_id": action_preset_id, **fields},
                execute=lambda conn: update_execute(conn, action_preset_id, fields),
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review action") from None
        except ValidationError as exc:
            raise map_validation_to_400(exc) from None
        return _finish_mutation_or_replay(result, build=build_action_response)

    update_action_endpoint.__annotations__["request"] = action_update_type

    def delete_action_endpoint(
        action_preset_id: int,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> Any:
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="DELETE",
                path=_idempotent_path(segment, f"actions/{action_preset_id}"),
                idempotency_key=idempotency_key,
                payload={"action_preset_id": action_preset_id},
                execute=lambda conn: delete_execute(conn, action_preset_id),
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review action") from None
        return _finish_mutation_or_replay(result, build=None)

    list_actions_endpoint.__name__ = f"list_{segment}_review_actions_endpoint"
    create_action_endpoint.__name__ = f"create_{segment}_review_action_endpoint"
    get_action_endpoint.__name__ = f"get_{segment}_review_action_endpoint"
    update_action_endpoint.__name__ = f"update_{segment}_review_action_endpoint"
    delete_action_endpoint.__name__ = f"delete_{segment}_review_action_endpoint"

    list_actions_response_model = cast(Any, GenericAlias(list, (action_response_model,)))
    router.add_api_route(
        f"/review/{segment}/actions",
        list_actions_endpoint,
        methods=["GET"],
        response_model=list_actions_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/actions",
        create_action_endpoint,
        methods=["POST"],
        response_model=action_response_model,
        status_code=201,
    )
    router.add_api_route(
        f"/review/{segment}/actions/{{action_preset_id}}",
        get_action_endpoint,
        methods=["GET"],
        response_model=action_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/actions/{{action_preset_id}}",
        update_action_endpoint,
        methods=["PATCH"],
        response_model=action_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/actions/{{action_preset_id}}",
        delete_action_endpoint,
        methods=["DELETE"],
        response_model=None,
    )

    return ReviewActionRouteHandles(
        list_actions=list_actions_endpoint,
        create_action=create_action_endpoint,
        get_action=get_action_endpoint,
        update_action=update_action_endpoint,
        delete_action=delete_action_endpoint,
    )


@dataclass(frozen=True)
class ReviewSessionRouteHandles:
    list_sessions: Callable[..., Any]
    create_session: Callable[..., Any]
    get_session: Callable[..., Any]
    move_session: Callable[..., Any]
    refresh_session: Callable[..., Any]
    update_session: Callable[..., Any]
    delete_session: Callable[..., Any]
    execute_session_action: Callable[..., Any]


def register_review_workflow_session_routes[
    SR: BaseModel,
    SN: BaseModel,
    SAR: BaseModel,
    SC: BaseModel,
    SU: BaseModel,
    SAQ: BaseModel,
](
    router: APIRouter,
    *,
    segment: str,
    session_row_response_model: type[SR],
    snapshot_response_model: type[SN],
    session_action_response_model: type[SAR],
    session_create_type: type[SC],
    session_update_type: type[SU],
    session_action_request_type: type[SAQ],
    list_sessions: Callable[[Any], list[Any]],
    build_session_response: Callable[[Any], Any],
    build_snapshot_response: Callable[[Any], Any],
    build_session_action_response: Callable[[Any], Any],
    create_session_execute: Callable[..., Any],
    get_session_snapshot: Callable[[Any, int, Settings], Any],
    move_session_execute: Callable[[Any, int, ReviewSessionMoveRequest, Settings], Any],
    refresh_session_execute: Callable[[Any, int, Settings], Any],
    patch_session_execute: Callable[[Any, int, dict[str, Any], Any, Settings], Any],
    delete_session_execute: Callable[[Any, int], Any],
    session_action_execute: Callable[..., Any],
) -> ReviewSessionRouteHandles:
    """Register `/review/{segment}/sessions*` routes shared by both workflows."""

    def list_sessions_endpoint(settings: SettingsDep) -> list[SR]:
        with db.core_connection(settings) as conn:
            sessions = list_sessions(conn)
        return [build_session_response(session) for session in sessions]

    def create_session_endpoint(
        request: Any,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> SN | JSONResponse:
        payload = request.model_dump(mode="json")
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="POST",
                path=_idempotent_path(segment, "sessions"),
                idempotency_key=idempotency_key,
                payload=payload,
                execute=lambda conn: create_session_execute(conn, request, settings),
                response_status=201,
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
        except LoopNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="loop") from None
        except ValidationError as exc:
            raise map_validation_to_400(exc) from None
        return _finish_mutation_or_replay(result, build=build_snapshot_response)

    create_session_endpoint.__annotations__["request"] = session_create_type

    def get_session_endpoint(
        session_id: int,
        settings: SettingsDep,
    ) -> SN:
        with db.core_connection(settings) as conn:
            try:
                snapshot = get_session_snapshot(conn, session_id, settings)
            except ResourceNotFoundError as exc:
                raise map_not_found_to_404(exc, resource_type="review session") from None
        return build_snapshot_response(snapshot)

    def move_session_endpoint(
        session_id: int,
        request: ReviewSessionMoveRequest,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> SN | JSONResponse:
        payload = {"session_id": session_id, **request.model_dump(mode="json")}
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="POST",
                path=_idempotent_path(segment, f"sessions/{session_id}/move"),
                idempotency_key=idempotency_key,
                payload=payload,
                execute=lambda conn: move_session_execute(conn, session_id, request, settings),
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
        except ValidationError as exc:
            raise map_validation_to_400(exc) from None
        return _finish_mutation_or_replay(result, build=build_snapshot_response)

    def refresh_session_endpoint(
        session_id: int,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> SN | JSONResponse:
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="POST",
                path=_idempotent_path(segment, f"sessions/{session_id}/refresh"),
                idempotency_key=idempotency_key,
                payload={"session_id": session_id},
                execute=lambda conn: refresh_session_execute(conn, session_id, settings),
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
        except ValidationError as exc:
            raise map_validation_to_400(exc) from None
        return _finish_mutation_or_replay(result, build=build_snapshot_response)

    def update_session_endpoint(
        session_id: int,
        request: Any,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> SN | JSONResponse:
        fields = request.model_dump(mode="json", exclude_unset=True)
        if not fields:
            raise no_fields_to_update_http_exception() from None
        current_loop_id = (
            fields["current_loop_id"] if "current_loop_id" in fields else review_workflows._UNSET
        )
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="PATCH",
                path=_idempotent_path(segment, f"sessions/{session_id}"),
                idempotency_key=idempotency_key,
                payload={"session_id": session_id, **fields},
                execute=lambda conn: patch_session_execute(
                    conn, session_id, fields, current_loop_id, settings
                ),
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
        except LoopNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="loop") from None
        except ValidationError as exc:
            raise map_validation_to_400(exc) from None
        return _finish_mutation_or_replay(result, build=build_snapshot_response)

    update_session_endpoint.__annotations__["request"] = session_update_type

    def delete_session_endpoint(
        session_id: int,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> Any:
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="DELETE",
                path=_idempotent_path(segment, f"sessions/{session_id}"),
                idempotency_key=idempotency_key,
                payload={"session_id": session_id},
                execute=lambda conn: delete_session_execute(conn, session_id),
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
        return _finish_mutation_or_replay(result, build=None)

    def execute_session_action_endpoint(
        session_id: int,
        request: Any,
        settings: SettingsDep,
        idempotency_key: str | None = IdempotencyKeyHeader,
    ) -> SAR | JSONResponse:
        payload = {"session_id": session_id, **request.model_dump(mode="json")}
        try:
            result = run_idempotent_loop_route(
                settings=settings,
                method="POST",
                path=_idempotent_path(segment, f"sessions/{session_id}/action"),
                idempotency_key=idempotency_key,
                payload=payload,
                execute=lambda conn: session_action_execute(conn, session_id, request, settings),
            )
        except ResourceNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="review session") from None
        except LoopNotFoundError as exc:
            raise map_not_found_to_404(exc, resource_type="loop") from None
        except ValidationError as exc:
            raise map_validation_to_400(exc) from None
        return _finish_mutation_or_replay(result, build=build_session_action_response)

    execute_session_action_endpoint.__annotations__["request"] = session_action_request_type

    list_sessions_endpoint.__name__ = f"list_{segment}_review_sessions_endpoint"
    create_session_endpoint.__name__ = f"create_{segment}_review_session_endpoint"
    get_session_endpoint.__name__ = f"get_{segment}_review_session_endpoint"
    move_session_endpoint.__name__ = f"move_{segment}_review_session_endpoint"
    refresh_session_endpoint.__name__ = f"refresh_{segment}_review_session_endpoint"
    update_session_endpoint.__name__ = f"update_{segment}_review_session_endpoint"
    delete_session_endpoint.__name__ = f"delete_{segment}_review_session_endpoint"
    execute_session_action_endpoint.__name__ = f"execute_{segment}_review_session_action_endpoint"

    list_sessions_response_model = cast(Any, GenericAlias(list, (session_row_response_model,)))
    router.add_api_route(
        f"/review/{segment}/sessions",
        list_sessions_endpoint,
        methods=["GET"],
        response_model=list_sessions_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/sessions",
        create_session_endpoint,
        methods=["POST"],
        response_model=snapshot_response_model,
        status_code=201,
    )
    router.add_api_route(
        f"/review/{segment}/sessions/{{session_id}}",
        get_session_endpoint,
        methods=["GET"],
        response_model=snapshot_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/sessions/{{session_id}}/move",
        move_session_endpoint,
        methods=["POST"],
        response_model=snapshot_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/sessions/{{session_id}}/refresh",
        refresh_session_endpoint,
        methods=["POST"],
        response_model=snapshot_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/sessions/{{session_id}}",
        update_session_endpoint,
        methods=["PATCH"],
        response_model=snapshot_response_model,
    )
    router.add_api_route(
        f"/review/{segment}/sessions/{{session_id}}",
        delete_session_endpoint,
        methods=["DELETE"],
        response_model=None,
    )
    router.add_api_route(
        f"/review/{segment}/sessions/{{session_id}}/action",
        execute_session_action_endpoint,
        methods=["POST"],
        response_model=session_action_response_model,
    )

    return ReviewSessionRouteHandles(
        list_sessions=list_sessions_endpoint,
        create_session=create_session_endpoint,
        get_session=get_session_endpoint,
        move_session=move_session_endpoint,
        refresh_session=refresh_session_endpoint,
        update_session=update_session_endpoint,
        delete_session=delete_session_endpoint,
        execute_session_action=execute_session_action_endpoint,
    )


__all__ = [
    "ReviewActionRouteHandles",
    "ReviewSessionRouteHandles",
    "register_review_workflow_action_routes",
    "register_review_workflow_session_routes",
]
