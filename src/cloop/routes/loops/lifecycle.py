"""Loop lifecycle endpoints.

Purpose:
    HTTP endpoints for capture, retrieval, mutation, close, status transition,
    and enrichment requests.

Responsibilities:
    - Create loops via capture orchestration
    - Read single loops
    - Apply canonical loop updates and status transitions
    - Run explicit enrichment synchronously while capture autopilot stays async

Non-scope:
    - Query/list/search endpoints
    - Import/export and metrics endpoints
    - Suggestion or clarification endpoints
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from ... import db
from ...loops import read_service as loop_read_service
from ...loops import service as loop_service
from ...loops.capture_orchestration import (
    CaptureFieldInputs,
    CaptureOrchestrationInput,
    CaptureStatusFlags,
    CaptureTemplateRef,
    orchestrate_capture,
)
from ...loops.enrichment_orchestration import orchestrate_loop_enrichment
from ...loops.errors import ValidationError
from ...loops.models import is_terminal_status
from ...schemas.loops import (
    LoopCaptureRequest,
    LoopCloseRequest,
    LoopEnrichmentResponse,
    LoopResponse,
    LoopStatusRequest,
    LoopUpdateRequest,
)
from ...settings import Settings
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_loop_enrichment_response,
    build_loop_response,
    no_fields_to_update_http_exception,
    run_idempotent_loop_route,
)

router = APIRouter()
_logger = logging.getLogger(__name__)


def _safe_enrich_loop(*, loop_id: int, settings: Settings) -> None:
    """Background task wrapper that catches enrichment exceptions."""
    from ...loops import enrichment as loop_enrichment

    try:
        loop_enrichment.enrich_loop(loop_id=loop_id, settings=settings)
    except KeyboardInterrupt, SystemExit:
        raise
    except ValueError as exc:
        _logger.warning(
            "Background enrichment configuration error for loop %s (error persisted to DB): %s",
            loop_id,
            exc,
        )
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "Background enrichment failed for loop %s (error persisted to DB): %s",
            loop_id,
            exc,
        )


@router.post("/capture", response_model=LoopResponse)
def loop_capture_endpoint(
    request: LoopCaptureRequest,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    payload = request.model_dump()
    input_data = CaptureOrchestrationInput(
        raw_text=request.raw_text,
        captured_at_iso=request.captured_at,
        client_tz_offset_min=request.client_tz_offset_min,
        status_flags=CaptureStatusFlags(
            actionable=request.actionable,
            blocked=request.blocked,
            scheduled=request.scheduled,
        ),
        schedule=request.schedule,
        rrule=request.rrule,
        timezone=request.timezone,
        template_ref=CaptureTemplateRef(
            template_id=request.template_id,
            template_name=request.template_name,
        ),
        field_inputs=CaptureFieldInputs(
            activation_energy=request.activation_energy,
            blocked_reason=request.blocked_reason,
            due_date=request.due_date,
            due_at_utc=request.due_at_utc,
            next_action=request.next_action,
            project=request.project,
            tags=request.tags,
            time_minutes=request.time_minutes,
        ),
    )

    result = run_idempotent_loop_route(
        settings=settings,
        method="POST",
        path="/loops/capture",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: build_loop_response(
            orchestrate_capture(
                input_data=input_data,
                settings=settings,
                conn=conn,
            ).loop
        ).model_dump(),
    )
    if isinstance(result, JSONResponse):
        return result

    if settings.autopilot_enabled:
        background_tasks.add_task(
            _safe_enrich_loop,
            loop_id=result["id"],
            settings=settings,
        )
    return build_loop_response(result)


@router.get("/{loop_id}", response_model=LoopResponse)
def loop_get_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        record = loop_read_service.get_loop(loop_id=loop_id, conn=conn)
    return build_loop_response(record)


@router.patch("/{loop_id}", response_model=LoopResponse)
def loop_update_endpoint(
    loop_id: int,
    request: LoopUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    fields = request.model_dump(exclude_unset=True)
    claim_token = fields.pop("claim_token", None)
    if not fields:
        raise no_fields_to_update_http_exception() from None

    payload = {"loop_id": loop_id, "fields": fields}

    result = run_idempotent_loop_route(
        settings=settings,
        method="PATCH",
        path=f"/loops/{loop_id}",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: build_loop_response(
            loop_service.update_loop(
                loop_id=loop_id,
                fields=fields,
                claim_token=claim_token,
                conn=conn,
            )
        ).model_dump(),
    )

    if isinstance(result, JSONResponse):
        return result
    return build_loop_response(result)


@router.post("/{loop_id}/close", response_model=LoopResponse)
def loop_close_endpoint(
    loop_id: int,
    request: LoopCloseRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    if not is_terminal_status(request.status):
        raise ValidationError("status", "must be completed or dropped")

    payload = {
        "loop_id": loop_id,
        "status": request.status.value,
        "note": request.note,
        "claim_token": request.claim_token,
    }

    result = run_idempotent_loop_route(
        settings=settings,
        method="POST",
        path=f"/loops/{loop_id}/close",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: build_loop_response(
            loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
                claim_token=request.claim_token,
            )
        ).model_dump(),
    )

    if isinstance(result, JSONResponse):
        return result
    return build_loop_response(result)


@router.post("/{loop_id}/status", response_model=LoopResponse)
def loop_status_endpoint(
    loop_id: int,
    request: LoopStatusRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    payload = {
        "loop_id": loop_id,
        "status": request.status.value,
        "note": request.note,
        "claim_token": request.claim_token,
    }

    result = run_idempotent_loop_route(
        settings=settings,
        method="POST",
        path=f"/loops/{loop_id}/status",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: build_loop_response(
            loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
                claim_token=request.claim_token,
            )
        ).model_dump(),
    )

    if isinstance(result, JSONResponse):
        return result
    return build_loop_response(result)


@router.post("/{loop_id}/enrich", response_model=LoopEnrichmentResponse)
def loop_enrich_endpoint(
    loop_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopEnrichmentResponse | JSONResponse:
    payload = {"loop_id": loop_id}

    result = run_idempotent_loop_route(
        settings=settings,
        method="POST",
        path=f"/loops/{loop_id}/enrich",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: build_loop_enrichment_response(
            orchestrate_loop_enrichment(
                loop_id=loop_id,
                conn=conn,
                settings=settings,
            ).to_payload()
        ).model_dump(),
    )
    if isinstance(result, JSONResponse):
        return result
    return build_loop_enrichment_response(result)
