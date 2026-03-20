"""Canonical application error contract shared across transports.

Purpose:
    Map domain and application exceptions to stable error codes, messages,
    details, and transport-specific renderers.

Responsibilities:
    - Normalize Cloop-owned exceptions into one structured error view
    - Provide HTTP response rendering for FastAPI handlers
    - Provide transport-friendly message extraction for CLI and MCP callers

Scope:
    - Exception-to-error-view mapping
    - Canonical HTTP JSON envelope rendering
    - Shared validation and internal-error response shaping

Non-scope:
    - Exception class definitions
    - Business logic or persistence
    - FastAPI route definitions

Usage:
    - Call `error_view_from_exception(...)` when a transport needs the canonical
      view of a handled exception.
    - Call `error_response(...)` to render one `AppErrorView` as JSON.

Invariants/Assumptions:
    - The same exception maps to the same code/message/details across transports.
    - Unsupported exception types fail fast instead of silently degrading.
    - Structured details remain JSON-serializable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from .ai_bridge.errors import (
    BridgeError,
    BridgeProcessError,
    BridgeProtocolError,
    BridgeStartupError,
    BridgeTimeoutError,
    BridgeUpstreamError,
)
from .constants import (
    HTTP_BAD_GATEWAY,
    HTTP_BAD_REQUEST,
    HTTP_CONFLICT,
    HTTP_FORBIDDEN,
    HTTP_GATEWAY_TIMEOUT,
    HTTP_INTERNAL_SERVER_ERROR,
    HTTP_NOT_FOUND,
    HTTP_SERVICE_UNAVAILABLE,
)
from .loops.errors import (
    ClaimExpiredError,
    ClaimNotFoundError,
    CloopError,
    DependencyCycleError,
    DependencyNotMetError,
    IdempotencyConflictAppError,
    InvalidIdempotencyKeyError,
    LoopClaimedError,
    LoopCreateError,
    LoopImportError,
    MergeConflictError,
    NoFieldsToUpdateError,
    NotFoundError,
    RecurrenceError,
    ResourceNotFoundError,
    TransitionError,
    UndoNotPossibleError,
    ValidationError,
    WorkingSetUndoNotPossibleError,
)


@dataclass(frozen=True, slots=True)
class AppErrorView:
    """Canonical error payload used across HTTP, MCP, and CLI transports."""

    error_type: str
    code: str
    message: str
    details: dict[str, Any]
    status_code: int


ErrorMapper = Callable[[Exception], AppErrorView | None]


def error_view_from_exception(exc: Exception) -> AppErrorView:
    """Normalize one application/domain exception into a canonical error view."""
    for mapper in (_map_cloop_error, _map_bridge_error, _map_http_exception):
        view = mapper(exc)
        if view is not None:
            return view
    raise TypeError(f"unsupported_error_view:{type(exc).__name__}")


def _map_cloop_error(exc: Exception) -> AppErrorView | None:
    """Map Cloop domain/application exceptions into the canonical error view."""
    if not isinstance(exc, CloopError):
        return None

    for mapper in (
        _map_claim_error,
        _map_idempotency_error,
        _map_validation_error,
        _map_dependency_error,
        _map_conflict_error,
        _map_not_found_error,
        _map_persistence_error,
        _map_generic_cloop_error,
    ):
        view = mapper(exc)
        if view is not None:
            return view
    return None


def _map_claim_error(exc: CloopError) -> AppErrorView | None:
    """Map claim and lease lifecycle failures."""
    if isinstance(exc, LoopClaimedError):
        return _build_error_view(
            error_type="loop_claimed",
            code="loop_claimed",
            message=exc.message,
            details={"loop_id": exc.loop_id, "owner": exc.owner, "lease_until": exc.lease_until},
            status_code=HTTP_CONFLICT,
        )
    if isinstance(exc, ClaimNotFoundError):
        return _build_error_view(
            error_type="invalid_claim_token",
            code="invalid_claim_token",
            message=exc.message,
            details={"loop_id": exc.loop_id},
            status_code=HTTP_FORBIDDEN,
        )
    if isinstance(exc, ClaimExpiredError):
        return _build_error_view(
            error_type="claim_expired",
            code="claim_expired",
            message=exc.message,
            details={"loop_id": exc.loop_id},
            status_code=410,
        )
    return None


def _map_idempotency_error(exc: CloopError) -> AppErrorView | None:
    """Map idempotency validation and conflict failures."""
    if isinstance(exc, NoFieldsToUpdateError):
        return _build_error_view(
            error_type="validation_error",
            code="no_fields_to_update",
            message=exc.message,
            details={},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, InvalidIdempotencyKeyError):
        return _build_error_view(
            error_type="validation_error",
            code="invalid_idempotency_key",
            message=exc.message,
            details=_detail_dict(exc),
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, IdempotencyConflictAppError):
        return _build_error_view(
            error_type="idempotency_conflict",
            code="idempotency_key_conflict",
            message=exc.message,
            details=_detail_dict(exc),
            status_code=HTTP_CONFLICT,
        )
    return None


def _map_validation_error(exc: CloopError) -> AppErrorView | None:
    """Map validation-oriented domain errors."""
    if isinstance(exc, TransitionError):
        return _build_error_view(
            error_type="transition_error",
            code="transition_error",
            message=exc.message,
            details={
                "from_status": exc.from_status,
                "to_status": exc.to_status,
                "detail": exc.detail,
            },
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, ValidationError):
        return _build_error_view(
            error_type="validation_error",
            code="validation_error",
            message=exc.message,
            details={"field": exc.field, "reason": exc.reason, "detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, RecurrenceError):
        return _build_error_view(
            error_type="recurrence_error",
            code="recurrence_error",
            message=exc.message,
            details=_detail_dict(exc),
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, UndoNotPossibleError):
        return _build_error_view(
            error_type="undo_not_possible",
            code="undo_not_possible",
            message=exc.message,
            details={"loop_id": exc.loop_id, "reason": exc.reason, "detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, WorkingSetUndoNotPossibleError):
        return _build_error_view(
            error_type="undo_not_possible",
            code="undo_not_possible",
            message=exc.message,
            details={
                "subject_type": exc.subject_type,
                "subject_id": exc.subject_id,
                "reason": exc.reason,
                "detail": exc.detail,
            },
            status_code=HTTP_BAD_REQUEST,
        )
    return None


def _map_dependency_error(exc: CloopError) -> AppErrorView | None:
    """Map dependency and workflow-graph validation failures."""
    if isinstance(exc, DependencyCycleError):
        return _build_error_view(
            error_type="dependency_cycle",
            code="dependency_cycle",
            message=exc.message,
            details=_detail_dict(exc),
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, DependencyNotMetError):
        return _build_error_view(
            error_type="dependency_not_met",
            code="dependency_not_met",
            message=exc.message,
            details={"detail": exc.detail, "open_dependencies": exc.open_dependencies},
            status_code=HTTP_BAD_REQUEST,
        )
    return None


def _map_conflict_error(exc: CloopError) -> AppErrorView | None:
    """Map domain conflicts that are not claim- or idempotency-specific."""
    if isinstance(exc, MergeConflictError):
        return _build_error_view(
            error_type="merge_conflict",
            code="merge_conflict",
            message=exc.message,
            details=_detail_dict(exc),
            status_code=HTTP_CONFLICT,
        )
    return None


def _map_not_found_error(exc: CloopError) -> AppErrorView | None:
    """Map resource lookup failures."""
    if isinstance(exc, ResourceNotFoundError):
        return _build_error_view(
            error_type="not_found",
            code=f"{exc.resource_type}_not_found",
            message=exc.message,
            details={"resource_type": exc.resource_type, "detail": exc.detail},
            status_code=HTTP_NOT_FOUND,
        )
    if isinstance(exc, NotFoundError):
        return _build_error_view(
            error_type="not_found",
            code="not_found",
            message=exc.message,
            details=_detail_dict(exc),
            status_code=HTTP_NOT_FOUND,
        )
    return None


def _map_persistence_error(exc: CloopError) -> AppErrorView | None:
    """Map storage/persistence failures."""
    if isinstance(exc, (LoopCreateError, LoopImportError)):
        return _build_error_view(
            error_type="persistence_error",
            code="persistence_error",
            message=exc.message,
            details=_detail_dict(exc),
            status_code=HTTP_INTERNAL_SERVER_ERROR,
        )
    return None


def _map_generic_cloop_error(exc: CloopError) -> AppErrorView | None:
    """Map the remaining Cloop domain errors to the generic contract."""
    return _build_error_view(
        error_type="domain_error",
        code="domain_error",
        message=exc.message,
        details=_detail_dict(exc),
        status_code=HTTP_BAD_REQUEST,
    )


def _map_bridge_error(exc: Exception) -> AppErrorView | None:
    """Map bridge/runtime failures from the pi bridge layer."""
    if isinstance(exc, (BridgeStartupError, BridgeProcessError)):
        return _string_detail_error_view(
            error_type="ai_backend_unavailable",
            code="ai_backend_unavailable",
            message=str(exc),
            status_code=HTTP_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, BridgeTimeoutError):
        return _string_detail_error_view(
            error_type="ai_backend_timeout",
            code="ai_backend_timeout",
            message=str(exc),
            status_code=HTTP_GATEWAY_TIMEOUT,
        )
    if isinstance(exc, BridgeProtocolError):
        return _string_detail_error_view(
            error_type="ai_backend_protocol_error",
            code="ai_backend_protocol_error",
            message=str(exc),
            status_code=HTTP_BAD_GATEWAY,
        )
    if isinstance(exc, BridgeUpstreamError):
        return _build_error_view(
            error_type="ai_backend_error",
            code=exc.code or "ai_backend_error",
            message=str(exc),
            details={"detail": str(exc), "retryable": exc.retryable},
            status_code=HTTP_SERVICE_UNAVAILABLE if exc.retryable else HTTP_BAD_GATEWAY,
        )
    if isinstance(exc, BridgeError):
        return _string_detail_error_view(
            error_type="ai_backend_error",
            code="ai_backend_error",
            message=str(exc),
            status_code=HTTP_BAD_GATEWAY,
        )
    return None


def _map_http_exception(exc: Exception) -> AppErrorView | None:
    """Map FastAPI HTTPException payloads into the canonical contract."""
    if not isinstance(exc, HTTPException):
        return None

    detail = _normalize_http_exception_detail(exc.detail)
    message = (
        detail.get("message") or detail.get("code") or detail.get("detail") or "Request failed"
    )
    code = detail.get("code") or "http_error"
    return _build_error_view(
        error_type="http_error",
        code=str(code),
        message=str(message),
        details=detail,
        status_code=exc.status_code,
    )


def _normalize_http_exception_detail(detail: Any) -> dict[str, Any]:
    """Normalize HTTPException detail payloads into one dict shape."""
    if isinstance(detail, dict):
        return dict(detail)
    return {"detail": detail}


def _detail_dict(exc: CloopError) -> dict[str, Any]:
    """Build a canonical detail-only payload from one Cloop exception."""
    return {"detail": exc.detail}


def _string_detail_error_view(
    *,
    error_type: str,
    code: str,
    message: str,
    status_code: int,
) -> AppErrorView:
    """Build one error view whose details mirror the rendered exception string."""
    return _build_error_view(
        error_type=error_type,
        code=code,
        message=message,
        details={"detail": message},
        status_code=status_code,
    )


def _build_error_view(
    *,
    error_type: str,
    code: str,
    message: str,
    details: dict[str, Any],
    status_code: int,
) -> AppErrorView:
    """Construct the canonical error view object."""
    return AppErrorView(
        error_type=error_type,
        code=code,
        message=message,
        details=details,
        status_code=status_code,
    )


def error_response(view: AppErrorView) -> JSONResponse:
    """Render a canonical HTTP JSON error envelope."""
    details = {"code": view.code, **view.details}
    return JSONResponse(
        status_code=view.status_code,
        content={
            "error": {
                "type": view.error_type,
                "code": view.code,
                "message": view.message,
                "details": details,
            }
        },
    )


def request_validation_error_view(exc: RequestValidationError) -> AppErrorView:
    """Normalize FastAPI request validation failures to the canonical contract."""
    serialized_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        normalized = dict(error)
        ctx = normalized.get("ctx")
        if isinstance(ctx, dict):
            normalized["ctx"] = {
                key: (str(value) if isinstance(value, Exception) else value)
                for key, value in ctx.items()
            }
        serialized_errors.append(normalized)
    return AppErrorView(
        error_type="validation_error",
        code="request_validation_error",
        message="Validation failed",
        details={"errors": serialized_errors},
        status_code=422,
    )


def internal_error_view(*, error_id: str) -> AppErrorView:
    """Build the canonical response for unexpected internal failures."""
    return AppErrorView(
        error_type="server_error",
        code="internal_server_error",
        message="Unexpected server error",
        details={"error_id": error_id},
        status_code=HTTP_INTERNAL_SERVER_ERROR,
    )
