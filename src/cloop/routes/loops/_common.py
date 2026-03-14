"""Common utilities for loop routes.

Purpose:
    Shared dependencies, types, and helper functions used across
    all loop route modules.

Responsibilities:
    - Define common FastAPI dependencies (SettingsDep)
    - Define idempotency key header parameter
    - Provide helpers for idempotent mutation routes
    - Standardize common loop route error payloads and response conversion

Non-scope:
    - Does not contain endpoint implementations
    - Does not define Pydantic schemas or request/response models
    - Does not interact with database directly
"""

from collections.abc import Callable
from typing import Annotated, Any, Mapping, Sequence

from fastapi import Depends, Header
from fastapi.responses import JSONResponse

from ... import db
from ...idempotency_flow import (
    finalize_idempotent_response,
    prepare_http_idempotency,
    replay_http_response,
)
from ...loops.errors import (
    LoopClaimedError,
    NoFieldsToUpdateError,
    NotFoundError,
    ResourceNotFoundError,
    ValidationError,
)
from ...schemas.loops import (
    BulkResultItem,
    ClarificationResponse,
    ClarificationSubmitResponse,
    DependencyInfo,
    LoopCommentResponse,
    LoopEnrichmentResponse,
    LoopResponse,
    LoopTemplateResponse,
    LoopViewResponse,
    LoopWithDependenciesResponse,
    SuggestionListResponse,
    SuggestionResponse,
    TimerStatusResponse,
    TimeSessionResponse,
    WebhookDeliveryResponse,
    WebhookSubscriptionCreateResponse,
    WebhookSubscriptionResponse,
)
from ...settings import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
IdempotencyKeyHeader = Header(
    default=None,
    alias="Idempotency-Key",
    description=(
        "Unique key for idempotent requests. Re-sending the same request "
        "with this key returns the original response. "
        "Format: UUID v4 or prefixed UUID (e.g., 'req_550e8400-e29b-41d4-a716-446655440000'). "
        "Max length: 255 characters."
    ),
)


def run_idempotent_loop_route(
    *,
    settings: Settings,
    method: str,
    path: str,
    idempotency_key: str | None,
    payload: Mapping[str, Any],
    execute: Callable[[Any], Any],
    response_status: int = 200,
) -> JSONResponse | Any:
    """Run a mutation route with shared connection and idempotency handling."""
    with db.core_connection(settings) as conn:
        idempotency = prepare_http_idempotency(
            method=method,
            path=path,
            idempotency_key=idempotency_key,
            payload=payload,
            settings=settings,
            conn=conn,
        )
        replay = replay_http_response(idempotency)
        if replay is not None:
            return replay

        response_body = execute(conn)
        finalize_idempotent_response(
            state=idempotency,
            response_status=response_status,
            response_body=response_body,
            conn=conn,
        )
        return response_body


def loop_claimed_http_exception(exc: LoopClaimedError) -> LoopClaimedError:
    """Return the canonical loop-claimed domain exception."""
    return exc


def invalid_claim_token_http_exception() -> ResourceNotFoundError:
    """Return the canonical invalid-claim-token application error."""
    return ResourceNotFoundError("claim", "Invalid or expired claim token")


def claim_not_found_http_exception(*, loop_id: int) -> ResourceNotFoundError:
    """Return the canonical missing-claim application error."""
    return ResourceNotFoundError("claim", f"No valid claim for loop {loop_id}")


def no_fields_to_update_http_exception() -> NoFieldsToUpdateError:
    """Return the canonical no-fields-to-update domain exception."""
    return NoFieldsToUpdateError()


def map_not_found_to_404(
    exc: NotFoundError | None = None,
    *,
    resource_type: str,
    message: str | None = None,
) -> NotFoundError:
    """Return the canonical domain not-found exception for a named resource."""
    resolved_message = message or (
        exc.message if exc is not None else f"{resource_type.capitalize()} not found"
    )
    return ResourceNotFoundError(resource_type, resolved_message)


def map_validation_to_400(exc: ValidationError) -> ValidationError:
    """Return the canonical domain validation exception unchanged."""
    return exc


def build_loop_response(loop: Mapping[str, Any]) -> LoopResponse:
    """Convert a loop payload into the route response model."""
    return LoopResponse(**loop)


def build_loop_responses(loops: Sequence[Mapping[str, Any]]) -> list[LoopResponse]:
    """Convert multiple loop payloads into route response models."""
    return [build_loop_response(loop) for loop in loops]


def build_loop_enrichment_response(result: Mapping[str, Any]) -> LoopEnrichmentResponse:
    """Convert an enrichment payload into the route response model."""
    return LoopEnrichmentResponse(
        loop=build_loop_response(result["loop"]),
        suggestion_id=result["suggestion_id"],
        applied_fields=list(result.get("applied_fields") or []),
        needs_clarification=list(result.get("needs_clarification") or []),
    )


def build_clarification_response(clarification: Mapping[str, Any]) -> ClarificationResponse:
    """Convert a clarification payload into the route response model."""
    return ClarificationResponse(**clarification)


def build_clarification_responses(
    clarifications: Sequence[Mapping[str, Any]],
) -> list[ClarificationResponse]:
    """Convert multiple clarification payloads into route response models."""
    return [build_clarification_response(clarification) for clarification in clarifications]


def build_clarification_submit_response(
    result: Mapping[str, Any],
) -> ClarificationSubmitResponse:
    """Convert a clarification-submission payload into the route response model."""
    return ClarificationSubmitResponse(
        loop_id=result["loop_id"],
        answered_count=result["answered_count"],
        clarifications=build_clarification_responses(result.get("clarifications", [])),
        superseded_suggestion_ids=list(result.get("superseded_suggestion_ids") or []),
        message=result.get(
            "message",
            "Clarifications recorded. Re-enrich to generate an updated suggestion.",
        ),
    )


def build_suggestion_response(suggestion: Mapping[str, Any]) -> SuggestionResponse:
    """Convert a suggestion payload into the route response model."""
    return SuggestionResponse(
        id=int(suggestion["id"]),
        loop_id=int(suggestion["loop_id"]),
        suggestion_json=str(suggestion["suggestion_json"]),
        parsed=dict(suggestion["parsed"]),
        clarifications=build_clarification_responses(suggestion.get("clarifications", [])),
        model=str(suggestion["model"]),
        created_at=str(suggestion["created_at"]),
        resolution=str(suggestion["resolution"])
        if suggestion.get("resolution") is not None
        else None,
        resolved_at=(
            str(suggestion["resolved_at"]) if suggestion.get("resolved_at") is not None else None
        ),
        resolved_fields_json=(
            str(suggestion["resolved_fields_json"])
            if suggestion.get("resolved_fields_json") is not None
            else None
        ),
    )


def build_suggestion_list_response(
    suggestions: Sequence[Mapping[str, Any]],
) -> SuggestionListResponse:
    """Convert suggestion payloads into the list response model."""
    return SuggestionListResponse(
        suggestions=[build_suggestion_response(suggestion) for suggestion in suggestions],
        count=len(suggestions),
    )


def build_dependency_info_response(dep: Mapping[str, Any]) -> DependencyInfo:
    """Convert a dependency payload into the route response model."""
    return DependencyInfo(**dep)


def build_dependency_info_responses(
    deps: Sequence[Mapping[str, Any]],
) -> list[DependencyInfo]:
    """Convert multiple dependency payloads into route response models."""
    return [build_dependency_info_response(dep) for dep in deps]


def build_loop_with_dependencies_response(
    result: Mapping[str, Any],
) -> LoopWithDependenciesResponse:
    """Convert a loop-with-dependencies payload into the route response model."""
    return LoopWithDependenciesResponse(**result)


def build_loop_comment_response(comment: Mapping[str, Any]) -> LoopCommentResponse:
    """Convert a nested loop comment payload into the route response model."""
    replies = [build_loop_comment_response(reply) for reply in comment.get("replies", [])]
    return LoopCommentResponse(
        id=comment["id"],
        loop_id=comment["loop_id"],
        parent_id=comment.get("parent_id"),
        author=comment["author"],
        body_md=comment["body_md"],
        created_at_utc=comment["created_at_utc"],
        updated_at_utc=comment["updated_at_utc"],
        deleted_at_utc=comment.get("deleted_at_utc"),
        is_deleted=comment["is_deleted"],
        is_reply=comment["is_reply"],
        replies=replies,
    )


def build_bulk_result_items(results: Sequence[Mapping[str, Any]]) -> list[BulkResultItem]:
    """Convert service bulk-operation results into response envelopes."""
    return [
        BulkResultItem(
            index=result["index"],
            loop_id=result["loop_id"],
            ok=result["ok"],
            loop=build_loop_response(result["loop"]) if result.get("loop") else None,
            error=result.get("error"),
        )
        for result in results
    ]


def build_query_bulk_preview_response(result: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a dry-run bulk result into preview response kwargs."""
    return {
        "query": result["query"],
        "dry_run": True,
        "matched_count": result["matched_count"],
        "limited": result.get("limited", False),
        "targets": build_loop_responses(result.get("targets", [])),
    }


def build_loop_view_response(view: Mapping[str, Any]) -> LoopViewResponse:
    """Convert a saved view record into the route response model."""
    return LoopViewResponse(
        id=view["id"],
        name=view["name"],
        query=view["query"],
        description=view.get("description"),
        created_at_utc=view["created_at"],
        updated_at_utc=view["updated_at"],
    )


def build_loop_template_response(template: Mapping[str, Any]) -> LoopTemplateResponse:
    """Convert a template record into the route response model."""
    import json

    return LoopTemplateResponse(
        id=template["id"],
        name=template["name"],
        description=template["description"],
        raw_text_pattern=template["raw_text_pattern"],
        defaults=json.loads(template["defaults_json"]) if template["defaults_json"] else {},
        is_system=bool(template["is_system"]),
        created_at=template["created_at"],
        updated_at=template["updated_at"],
    )


def build_timer_session_response(session: Any) -> TimeSessionResponse:
    """Convert a time-session model into the route response model."""
    return TimeSessionResponse.from_session(session)


def build_timer_status_response(status: Any) -> TimerStatusResponse:
    """Convert a timer-status model into the route response model."""
    return TimerStatusResponse.from_status(status)


def build_webhook_subscription_response(subscription: Any) -> WebhookSubscriptionResponse:
    """Convert a webhook subscription model into the route response model."""
    return WebhookSubscriptionResponse(
        id=subscription.id,
        url=subscription.url,
        event_types=subscription.event_types,
        active=subscription.active,
        description=subscription.description,
        created_at_utc=subscription.created_at,
        updated_at_utc=subscription.updated_at,
    )


def build_webhook_subscription_create_response(
    subscription: Any,
    *,
    secret: str,
) -> WebhookSubscriptionCreateResponse:
    """Convert a created webhook subscription into the create response model."""
    return WebhookSubscriptionCreateResponse(
        **build_webhook_subscription_response(subscription).model_dump(),
        secret=secret,
    )


def build_webhook_delivery_response(delivery: Any) -> WebhookDeliveryResponse:
    """Convert a webhook delivery model into the route response model."""
    return WebhookDeliveryResponse(
        id=delivery.id,
        subscription_id=delivery.subscription_id,
        event_id=delivery.event_id,
        event_type=delivery.event_type,
        status=delivery.status.value,
        http_status=delivery.http_status,
        error_message=delivery.error_message,
        attempt_count=delivery.attempt_count,
        next_retry_at=delivery.next_retry_at,
        created_at_utc=delivery.created_at,
        updated_at_utc=delivery.updated_at,
    )
