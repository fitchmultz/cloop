"""Core loop CRUD endpoints.

Purpose:
    HTTP endpoints for core loop operations: capture, list, get, update, close,
    status transition, and enrichment.

Responsibilities:
    - Create, read, update, and close loops
    - Transition loop status through state machine
    - List and filter loops by status, tags, or query
    - AI enrichment for loop titles and descriptions
    - Export and import loop data
    - Generate operational metrics
    - Manage active claims on loops

Non-scope:
    - Timer/time tracking (see timers.py)
    - Webhook subscription management (see webhooks.py)
    - Template management (see templates.py)
    - Dependency management (see dependencies.py)
    - Scheduler periodic tasks (see scheduler.py)

Endpoints:
- POST /loops/capture: Create new loop
- GET /loops: List loops (filtered by status/tag)
- GET /loops/tags: List all tags
- GET /loops/export: Export all loops
- POST /loops/import: Import loops
- GET /loops/next: Prioritized "Next Actions"
- GET /loops/review: Review cohorts for maintenance
- POST /loops/search: Search using DSL query language
- GET /loops/metrics: Operational metrics
- GET /loops/claims: List all active claims
- GET /loops/{loop_id}: Get single loop
- PATCH /loops/{loop_id}: Update loop fields
- POST /loops/{loop_id}/close: Close loop (completed/dropped)
- POST /loops/{loop_id}/status: Transition status
- POST /loops/{loop_id}/enrich: Request AI enrichment
"""

from typing import TYPE_CHECKING, Annotated, Any, List, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse

from ... import db
from ...constants import DEFAULT_LOOP_LIST_LIMIT, DEFAULT_LOOP_NEXT_LIMIT
from ...idempotency import (
    IdempotencyConflictError,
    build_http_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ...loops import enrichment as loop_enrichment
from ...loops import service as loop_service
from ...loops.errors import ClaimNotFoundError, LoopClaimedError
from ...loops.metrics import compute_loop_metrics, get_operation_metrics
from ...loops.models import LoopStatus, is_terminal_status, resolve_status_from_flags, utc_now
from ...loops.utils import normalize_tag
from ...schemas.loops import (
    ApplySuggestionRequest,
    ApplySuggestionResponse,
    LoopCaptureRequest,
    LoopClaimStatusResponse,
    LoopCloseRequest,
    LoopExportItem,
    LoopExportResponse,
    LoopImportRequest,
    LoopImportResponse,
    LoopMetricsResponse,
    LoopNextResponse,
    LoopOperationMetricsResponse,
    LoopResponse,
    LoopReviewCohortItem,
    LoopReviewCohortResponse,
    LoopReviewResponse,
    LoopSearchRequest,
    LoopSearchResponse,
    LoopStatusCountsResponse,
    LoopStatusRequest,
    LoopUpdateRequest,
    RejectSuggestionResponse,
    SuggestionListResponse,
    SuggestionResponse,
)
from ._common import IdempotencyKeyHeader, SettingsDep, _idempotency_conflict

if TYPE_CHECKING:
    from ...loops.metrics import LoopMetrics

router = APIRouter()


def _metrics_to_response(metrics: "LoopMetrics") -> LoopMetricsResponse:
    """Convert LoopMetrics dataclass to LoopMetricsResponse."""
    return LoopMetricsResponse(
        generated_at_utc=metrics.generated_at_utc,
        total_loops=metrics.total_loops,
        status_counts=LoopStatusCountsResponse(
            inbox=metrics.status_counts.inbox,
            actionable=metrics.status_counts.actionable,
            blocked=metrics.status_counts.blocked,
            scheduled=metrics.status_counts.scheduled,
            completed=metrics.status_counts.completed,
            dropped=metrics.status_counts.dropped,
        ),
        stale_open_count=metrics.stale_open_count,
        blocked_too_long_count=metrics.blocked_too_long_count,
        no_next_action_count=metrics.no_next_action_count,
        enrichment_pending_count=metrics.enrichment_pending_count,
        enrichment_failed_count=metrics.enrichment_failed_count,
        capture_count_24h=metrics.capture_count_24h,
        completion_count_24h=metrics.completion_count_24h,
        avg_age_open_hours=metrics.avg_age_open_hours,
    )


@router.post("/capture", response_model=LoopResponse)
def loop_capture_endpoint(
    request: LoopCaptureRequest,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    # Resolve status from flags initially
    status = resolve_status_from_flags(
        scheduled=request.scheduled,
        blocked=request.blocked,
        actionable=request.actionable,
    )

    # Resolve recurrence RRULE from schedule phrase or direct rrule
    recurrence_rrule: str | None = None
    if request.schedule:
        from ...loops.recurrence import parse_recurrence_schedule

        try:
            parsed = parse_recurrence_schedule(request.schedule)
            recurrence_rrule = parsed.rrule
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid schedule: {e}") from None
    elif request.rrule:
        recurrence_rrule = request.rrule

    # Apply template if specified
    raw_text = request.raw_text
    template_defaults: dict[str, Any] = {}

    if request.template_id or request.template_name:
        from ...loops.repo import get_loop_template, get_loop_template_by_name
        from ...loops.templates import (
            apply_template_to_capture,
            extract_update_fields_from_template,
        )

        with db.core_connection(settings) as conn:
            if request.template_id:
                template = get_loop_template(template_id=request.template_id, conn=conn)
            else:
                template = get_loop_template_by_name(name=request.template_name or "", conn=conn)

        if template:
            applied = apply_template_to_capture(
                template=template,
                raw_text_override=request.raw_text,
                now_utc=utc_now(),
                tz_offset_min=request.client_tz_offset_min,
            )
            raw_text = applied["raw_text"]
            template_defaults = applied

            # Merge status flags from template if not explicitly set in request
            if not request.actionable and not request.scheduled and not request.blocked:
                status = resolve_status_from_flags(
                    scheduled=applied.get("scheduled", False),
                    blocked=applied.get("blocked", False),
                    actionable=applied.get("actionable", False),
                )

    # Build capture fields from request (rich capture metadata)
    capture_fields: dict[str, Any] = {}
    if request.due_at_utc:
        capture_fields["due_at_utc"] = request.due_at_utc
    if request.next_action:
        capture_fields["next_action"] = request.next_action
    if request.time_minutes:
        capture_fields["time_minutes"] = request.time_minutes
    if request.activation_energy is not None:
        capture_fields["activation_energy"] = request.activation_energy
    if request.project:
        capture_fields["project"] = request.project
    if request.tags:
        capture_fields["tags"] = request.tags

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", "/loops/capture")
        payload = request.model_dump()
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            record = loop_service.capture_loop(
                raw_text=raw_text,
                captured_at_iso=request.captured_at,
                client_tz_offset_min=request.client_tz_offset_min,
                status=status,
                conn=conn,
                recurrence_rrule=recurrence_rrule,
                recurrence_tz=request.timezone,
                capture_fields=capture_fields if capture_fields else None,
            )

            # Apply template defaults, skipping fields already in capture_fields
            if template_defaults:
                update_fields = extract_update_fields_from_template(template_defaults)
                if capture_fields:
                    update_fields = {
                        k: v for k, v in update_fields.items() if k not in capture_fields
                    }
                if update_fields:
                    record = loop_service.update_loop(
                        loop_id=record["id"],
                        fields=update_fields,
                        conn=conn,
                    )

            if settings.autopilot_enabled:
                record = loop_service.request_enrichment(loop_id=record["id"], conn=conn)

            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            record = loop_service.capture_loop(
                raw_text=raw_text,
                captured_at_iso=request.captured_at,
                client_tz_offset_min=request.client_tz_offset_min,
                status=status,
                conn=conn,
                recurrence_rrule=recurrence_rrule,
                recurrence_tz=request.timezone,
                capture_fields=capture_fields if capture_fields else None,
            )

            # Apply template defaults, skipping fields already in capture_fields
            if template_defaults:
                update_fields = extract_update_fields_from_template(template_defaults)
                if capture_fields:
                    update_fields = {
                        k: v for k, v in update_fields.items() if k not in capture_fields
                    }
                if update_fields:
                    record = loop_service.update_loop(
                        loop_id=record["id"],
                        fields=update_fields,
                        conn=conn,
                    )

            if settings.autopilot_enabled:
                record = loop_service.request_enrichment(loop_id=record["id"], conn=conn)
        response = LoopResponse(**record).model_dump()

    if settings.autopilot_enabled:
        background_tasks.add_task(
            loop_enrichment.enrich_loop,
            loop_id=record["id"],
            settings=settings,
        )
    return LoopResponse(**response)


@router.get("/", response_model=List[LoopResponse])
def loop_list_endpoint(
    settings: SettingsDep,
    status: Annotated[
        LoopStatus | Literal["all", "open"] | None,
        Query(description="Filter by loop status, 'open', or 'all'"),
    ] = "open",
    tag: Annotated[str | None, Query(description="Filter by tag")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_LOOP_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> List[LoopResponse]:
    tag_value = normalize_tag(tag)
    with db.core_connection(settings) as conn:
        if status == "open":
            statuses = [
                LoopStatus.INBOX,
                LoopStatus.ACTIONABLE,
                LoopStatus.BLOCKED,
                LoopStatus.SCHEDULED,
            ]
            if tag_value:
                loops = loop_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_service.list_loops_by_statuses(
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
        else:
            resolved_status = None if status is None or status == "all" else status
            if tag_value:
                statuses = [resolved_status] if resolved_status else None
                loops = loop_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_service.list_loops(
                    status=resolved_status, limit=limit, offset=offset, conn=conn
                )
    return [LoopResponse(**loop_item) for loop_item in loops]


@router.get("/tags", response_model=List[str])
def loop_tags_endpoint(settings: SettingsDep) -> List[str]:
    with db.core_connection(settings) as conn:
        return loop_service.list_tags(conn=conn)


@router.get("/export", response_model=LoopExportResponse)
def loop_export_endpoint(settings: SettingsDep) -> LoopExportResponse:
    with db.core_connection(settings) as conn:
        loops_data: list[dict[str, Any]] = loop_service.export_loops(conn=conn)
    export_items = [LoopExportItem(**loop_item) for loop_item in loops_data]
    return LoopExportResponse(version=1, loops=export_items)


@router.post("/import", response_model=LoopImportResponse)
def loop_import_endpoint(
    request: LoopImportRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopImportResponse | JSONResponse:
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", "/loops/import")
        payload = {"loops": [loop.model_dump() for loop in request.loops]}
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            imported = loop_service.import_loops(loops=request.loops, conn=conn)
            response = LoopImportResponse(imported=imported).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
            return LoopImportResponse(**response)

    with db.core_connection(settings) as conn:
        imported = loop_service.import_loops(loops=request.loops, conn=conn)
    return LoopImportResponse(imported=imported)


@router.get("/next", response_model=LoopNextResponse)
def loop_next_endpoint(
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=20)] = DEFAULT_LOOP_NEXT_LIMIT,
) -> LoopNextResponse:
    with db.core_connection(settings) as conn:
        result: dict[str, list[dict[str, Any]]] = loop_service.next_loops(limit=limit, conn=conn)
    return LoopNextResponse(
        due_soon=[LoopResponse(**item) for item in result["due_soon"]],
        quick_wins=[LoopResponse(**item) for item in result["quick_wins"]],
        high_leverage=[LoopResponse(**item) for item in result["high_leverage"]],
        standard=[LoopResponse(**item) for item in result["standard"]],
    )


@router.get("/review", response_model=LoopReviewResponse)
def loop_review_endpoint(
    settings: SettingsDep,
    daily: Annotated[bool, Query(description="Include daily cohorts")] = True,
    weekly: Annotated[bool, Query(description="Include weekly cohorts")] = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LoopReviewResponse:
    """Get review cohorts for daily/weekly maintenance.

    Returns deterministic cohorts:
    - stale: Open loops not updated in 72+ hours
    - no_next_action: Actionable/scheduled without next_action
    - blocked_too_long: Blocked for 48+ hours
    - due_soon_unplanned: Due within 48h but no next_action

    Daily includes all four cohorts. Weekly includes stale and blocked_too_long.
    Thresholds are configurable via environment variables.
    """
    from ...loops.models import utc_now
    from ...loops.review import compute_review_cohorts

    with db.core_connection(settings) as conn:
        result = compute_review_cohorts(
            settings=settings,
            now_utc=utc_now(),
            conn=conn,
            include_daily=daily,
            include_weekly=weekly,
            limit_per_cohort=limit,
        )

    return LoopReviewResponse(
        daily=[
            LoopReviewCohortResponse(
                cohort=c.cohort.value,
                count=c.count,
                items=[LoopReviewCohortItem(**item) for item in c.items],
            )
            for c in result.daily
        ],
        weekly=[
            LoopReviewCohortResponse(
                cohort=c.cohort.value,
                count=c.count,
                items=[LoopReviewCohortItem(**item) for item in c.items],
            )
            for c in result.weekly
        ],
        generated_at_utc=result.generated_at_utc,
    )


@router.post("/search", response_model=LoopSearchResponse)
def loop_search_endpoint(
    request: LoopSearchRequest,
    settings: SettingsDep,
) -> LoopSearchResponse:
    """Search loops using the DSL query language.

    This is the canonical query endpoint used by API, CLI, MCP, and UI.
    """
    with db.core_connection(settings) as conn:
        items = loop_service.search_loops_by_query(
            query=request.query,
            limit=request.limit,
            offset=request.offset,
            conn=conn,
        )
    return LoopSearchResponse(
        query=request.query,
        limit=request.limit,
        offset=request.offset,
        items=[LoopResponse(**item) for item in items],
    )


@router.get("/claims", response_model=List[LoopClaimStatusResponse])
def list_claims_endpoint(
    settings: SettingsDep,
    owner: Annotated[str | None, Query(description="Filter by owner")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> List[LoopClaimStatusResponse]:
    """List all active claims."""
    with db.core_connection(settings) as conn:
        claims = loop_service.list_active_claims(owner=owner, limit=limit, conn=conn)
    return [LoopClaimStatusResponse(**claim) for claim in claims]


@router.get("/metrics", response_model=LoopMetricsResponse)
def loop_metrics_endpoint(
    settings: SettingsDep,
) -> LoopMetricsResponse:
    """Get operational metrics for loop workflow health.

    Returns SLIs including:
    - Total loops and counts by status
    - Stale open loops (not updated in 72+ hours)
    - Blocked loops stuck for 48+ hours
    - Enrichment queue health (pending/failed)
    - Capture and completion rates (24h window)
    - Average age of open loops
    - Operation-level metrics (if enabled via CLOOP_OPERATION_METRICS_ENABLED)
    """
    from ...loops.models import utc_now

    with db.core_connection(settings) as conn:
        metrics = compute_loop_metrics(conn=conn, now_utc=utc_now())

    operation_metrics = None
    if settings.operation_metrics_enabled:
        op_metrics = get_operation_metrics().get_snapshot()
        operation_metrics = LoopOperationMetricsResponse(**op_metrics)

    return LoopMetricsResponse(
        generated_at_utc=metrics.generated_at_utc,
        total_loops=metrics.total_loops,
        status_counts=LoopStatusCountsResponse(
            inbox=metrics.status_counts.inbox,
            actionable=metrics.status_counts.actionable,
            blocked=metrics.status_counts.blocked,
            scheduled=metrics.status_counts.scheduled,
            completed=metrics.status_counts.completed,
            dropped=metrics.status_counts.dropped,
        ),
        stale_open_count=metrics.stale_open_count,
        blocked_too_long_count=metrics.blocked_too_long_count,
        no_next_action_count=metrics.no_next_action_count,
        enrichment_pending_count=metrics.enrichment_pending_count,
        enrichment_failed_count=metrics.enrichment_failed_count,
        capture_count_24h=metrics.capture_count_24h,
        completion_count_24h=metrics.completion_count_24h,
        avg_age_open_hours=metrics.avg_age_open_hours,
        operation_metrics=operation_metrics,
    )


@router.get("/{loop_id}", response_model=LoopResponse)
def loop_get_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        record = loop_service.get_loop(loop_id=loop_id, conn=conn)
    return LoopResponse(**record)


@router.patch("/{loop_id}", response_model=LoopResponse)
def loop_update_endpoint(
    loop_id: int,
    request: LoopUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    fields = request.model_dump(exclude_unset=True)
    claim_token = fields.pop("claim_token", None)  # Extract claim_token if present
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("PATCH", f"/loops/{loop_id}")
        payload = {"loop_id": loop_id, "fields": fields}
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            try:
                record = loop_service.update_loop(
                    loop_id=loop_id, fields=fields, claim_token=claim_token, conn=conn
                )
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            try:
                record = loop_service.update_loop(
                    loop_id=loop_id, fields=fields, claim_token=claim_token, conn=conn
                )
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None
        response = LoopResponse(**record).model_dump()

    return LoopResponse(**response)


@router.post("/{loop_id}/close", response_model=LoopResponse)
def loop_close_endpoint(
    loop_id: int,
    request: LoopCloseRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    if not is_terminal_status(request.status):
        raise HTTPException(status_code=400, detail="status must be completed or dropped")

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/close")
        payload = {
            "loop_id": loop_id,
            "status": request.status.value,
            "note": request.note,
            "claim_token": request.claim_token,
        }
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            try:
                record = loop_service.transition_status(
                    loop_id=loop_id,
                    to_status=request.status,
                    conn=conn,
                    note=request.note,
                    claim_token=request.claim_token,
                )
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            try:
                record = loop_service.transition_status(
                    loop_id=loop_id,
                    to_status=request.status,
                    conn=conn,
                    note=request.note,
                    claim_token=request.claim_token,
                )
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None
        response = LoopResponse(**record).model_dump()

    return LoopResponse(**response)


@router.post("/{loop_id}/status", response_model=LoopResponse)
def loop_status_endpoint(
    loop_id: int,
    request: LoopStatusRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/status")
        payload = {
            "loop_id": loop_id,
            "status": request.status.value,
            "note": request.note,
            "claim_token": request.claim_token,
        }
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            try:
                record = loop_service.transition_status(
                    loop_id=loop_id,
                    to_status=request.status,
                    conn=conn,
                    note=request.note,
                    claim_token=request.claim_token,
                )
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            try:
                record = loop_service.transition_status(
                    loop_id=loop_id,
                    to_status=request.status,
                    conn=conn,
                    note=request.note,
                    claim_token=request.claim_token,
                )
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None
        response = LoopResponse(**record).model_dump()

    return LoopResponse(**response)


@router.post("/{loop_id}/enrich", response_model=LoopResponse)
def loop_enrich_endpoint(
    loop_id: int,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/enrich")
        payload = {"loop_id": loop_id}
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            record = loop_service.request_enrichment(loop_id=loop_id, conn=conn)
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            record = loop_service.request_enrichment(loop_id=loop_id, conn=conn)
        response = LoopResponse(**record).model_dump()

    background_tasks.add_task(
        loop_enrichment.enrich_loop,
        loop_id=loop_id,
        settings=settings,
    )
    return LoopResponse(**response)


# =============================================================================
# Suggestion endpoints
# =============================================================================


@router.get("/{loop_id}/suggestions", response_model=SuggestionListResponse)
def get_loop_suggestions(
    loop_id: int,
    settings: SettingsDep,
    pending_only: bool = False,
) -> SuggestionListResponse:
    """List suggestions for a specific loop."""
    with db.core_connection(settings) as conn:
        suggestions = loop_service.list_loop_suggestions(
            loop_id=loop_id,
            pending_only=pending_only,
            limit=50,
            conn=conn,
        )
    return SuggestionListResponse(
        suggestions=[SuggestionResponse(**s) for s in suggestions],
        count=len(suggestions),
    )


@router.post("/suggestions/{suggestion_id}/apply", response_model=ApplySuggestionResponse)
def apply_suggestion_endpoint(
    suggestion_id: int,
    request: ApplySuggestionRequest,
    settings: SettingsDep,
) -> ApplySuggestionResponse:
    """Apply a suggestion to its loop."""
    from ...loops.errors import SuggestionNotFoundError
    from ...loops.errors import ValidationError as CloopValidationError

    with db.core_connection(settings) as conn:
        try:
            result = loop_service.apply_suggestion(
                suggestion_id=suggestion_id,
                fields=request.fields,
                conn=conn,
                settings=settings,
            )
        except SuggestionNotFoundError:
            raise HTTPException(status_code=404, detail="Suggestion not found") from None
        except CloopValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    return ApplySuggestionResponse(**result)


@router.post("/suggestions/{suggestion_id}/reject", response_model=RejectSuggestionResponse)
def reject_suggestion_endpoint(
    suggestion_id: int,
    settings: SettingsDep,
) -> RejectSuggestionResponse:
    """Reject a suggestion without applying it."""
    from ...loops.errors import SuggestionNotFoundError
    from ...loops.errors import ValidationError as CloopValidationError

    with db.core_connection(settings) as conn:
        try:
            result = loop_service.reject_suggestion(suggestion_id=suggestion_id, conn=conn)
        except SuggestionNotFoundError:
            raise HTTPException(status_code=404, detail="Suggestion not found") from None
        except CloopValidationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    return RejectSuggestionResponse(**result)


@router.get("/suggestions/pending", response_model=SuggestionListResponse)
def list_pending_suggestions_endpoint(
    settings: SettingsDep,
    limit: int = 50,
) -> SuggestionListResponse:
    """List all suggestions awaiting resolution across all loops."""
    with db.core_connection(settings) as conn:
        suggestions = loop_service.list_loop_suggestions(
            pending_only=True,
            limit=limit,
            conn=conn,
        )
    return SuggestionListResponse(
        suggestions=[SuggestionResponse(**s) for s in suggestions],
        count=len(suggestions),
    )
