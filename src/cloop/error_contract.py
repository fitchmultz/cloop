"""Canonical application error contract shared across transports.

Purpose:
    Map domain/application exceptions to stable codes, messages, details, and
    transport-specific rendering.

Responsibilities:
    - Normalize Cloop-owned exceptions into one structured error view
    - Provide HTTP response rendering for FastAPI handlers
    - Provide transport-friendly message extraction for MCP/CLI callers

Non-scope:
    - Business logic or persistence
    - FastAPI route definitions
    - Exception class definitions
"""

from __future__ import annotations

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
)


@dataclass(frozen=True, slots=True)
class AppErrorView:
    """Canonical error payload used across HTTP, MCP, and CLI transports."""

    error_type: str
    code: str
    message: str
    details: dict[str, Any]
    status_code: int


def error_view_from_exception(exc: Exception) -> AppErrorView:
    """Normalize one application/domain exception into a canonical error view."""
    if isinstance(exc, LoopClaimedError):
        return AppErrorView(
            error_type="loop_claimed",
            code="loop_claimed",
            message=exc.message,
            details={"loop_id": exc.loop_id, "owner": exc.owner, "lease_until": exc.lease_until},
            status_code=HTTP_CONFLICT,
        )
    if isinstance(exc, ClaimNotFoundError):
        return AppErrorView(
            error_type="invalid_claim_token",
            code="invalid_claim_token",
            message=exc.message,
            details={"loop_id": exc.loop_id},
            status_code=HTTP_FORBIDDEN,
        )
    if isinstance(exc, ClaimExpiredError):
        return AppErrorView(
            error_type="claim_expired",
            code="claim_expired",
            message=exc.message,
            details={"loop_id": exc.loop_id},
            status_code=410,
        )
    if isinstance(exc, NoFieldsToUpdateError):
        return AppErrorView(
            error_type="validation_error",
            code="no_fields_to_update",
            message=exc.message,
            details={},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, InvalidIdempotencyKeyError):
        return AppErrorView(
            error_type="validation_error",
            code="invalid_idempotency_key",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, IdempotencyConflictAppError):
        return AppErrorView(
            error_type="idempotency_conflict",
            code="idempotency_key_conflict",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_CONFLICT,
        )
    if isinstance(exc, TransitionError):
        return AppErrorView(
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
        return AppErrorView(
            error_type="validation_error",
            code="validation_error",
            message=exc.message,
            details={"field": exc.field, "reason": exc.reason, "detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, RecurrenceError):
        return AppErrorView(
            error_type="recurrence_error",
            code="recurrence_error",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, DependencyCycleError):
        return AppErrorView(
            error_type="dependency_cycle",
            code="dependency_cycle",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, DependencyNotMetError):
        return AppErrorView(
            error_type="dependency_not_met",
            code="dependency_not_met",
            message=exc.message,
            details={"detail": exc.detail, "open_dependencies": exc.open_dependencies},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, MergeConflictError):
        return AppErrorView(
            error_type="merge_conflict",
            code="merge_conflict",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_CONFLICT,
        )
    if isinstance(exc, UndoNotPossibleError):
        return AppErrorView(
            error_type="undo_not_possible",
            code="undo_not_possible",
            message=exc.message,
            details={"loop_id": exc.loop_id, "reason": exc.reason, "detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, ResourceNotFoundError):
        return AppErrorView(
            error_type="not_found",
            code=f"{exc.resource_type}_not_found",
            message=exc.message,
            details={"resource_type": exc.resource_type, "detail": exc.detail},
            status_code=HTTP_NOT_FOUND,
        )
    if isinstance(exc, NotFoundError):
        return AppErrorView(
            error_type="not_found",
            code="not_found",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_NOT_FOUND,
        )
    if isinstance(exc, (LoopCreateError, LoopImportError)):
        return AppErrorView(
            error_type="persistence_error",
            code="persistence_error",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_INTERNAL_SERVER_ERROR,
        )
    if isinstance(exc, CloopError):
        return AppErrorView(
            error_type="domain_error",
            code="domain_error",
            message=exc.message,
            details={"detail": exc.detail},
            status_code=HTTP_BAD_REQUEST,
        )
    if isinstance(exc, BridgeStartupError | BridgeProcessError):
        return AppErrorView(
            error_type="ai_backend_unavailable",
            code="ai_backend_unavailable",
            message=str(exc),
            details={"detail": str(exc)},
            status_code=HTTP_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, BridgeTimeoutError):
        return AppErrorView(
            error_type="ai_backend_timeout",
            code="ai_backend_timeout",
            message=str(exc),
            details={"detail": str(exc)},
            status_code=HTTP_GATEWAY_TIMEOUT,
        )
    if isinstance(exc, BridgeProtocolError):
        return AppErrorView(
            error_type="ai_backend_protocol_error",
            code="ai_backend_protocol_error",
            message=str(exc),
            details={"detail": str(exc)},
            status_code=HTTP_BAD_GATEWAY,
        )
    if isinstance(exc, BridgeUpstreamError):
        return AppErrorView(
            error_type="ai_backend_error",
            code=exc.code or "ai_backend_error",
            message=str(exc),
            details={"detail": str(exc), "retryable": exc.retryable},
            status_code=HTTP_SERVICE_UNAVAILABLE if exc.retryable else HTTP_BAD_GATEWAY,
        )
    if isinstance(exc, BridgeError):
        return AppErrorView(
            error_type="ai_backend_error",
            code="ai_backend_error",
            message=str(exc),
            details={"detail": str(exc)},
            status_code=HTTP_BAD_GATEWAY,
        )
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        message = (
            detail.get("message") or detail.get("code") or detail.get("detail") or "Request failed"
        )
        code = detail.get("code") or "http_error"
        return AppErrorView(
            error_type="http_error",
            code=code,
            message=str(message),
            details=detail,
            status_code=exc.status_code,
        )
    raise TypeError(f"unsupported_error_view:{type(exc).__name__}")


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
