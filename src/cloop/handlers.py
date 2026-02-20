"""HTTP exception handlers for FastAPI application.

Purpose:
    Provide centralized exception handling that maps domain exceptions
    to appropriate HTTP responses.

Responsibilities:
    - Map NotFoundError -> 404 responses
    - Map ValidationError -> 422 responses
    - Handle unexpected exceptions -> 500 responses

Non-scope:
    - Domain exception definitions (see loops/errors.py)
    - Business logic (see loops/service.py)

Exception Mapping:
    - NotFoundError -> 404
- TransitionError -> 400
- ValidationError -> 400
- DependencyCycleError -> 400 (dependency would create cycle)
- DependencyNotMetError -> 400 (open dependencies block transition)
- RequestValidationError -> 422
- HTTPException -> Passthrough to status code
- Exception -> 500 (with error_id for log correlation)
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .constants import (
    HTTP_BAD_REQUEST,
    HTTP_INTERNAL_SERVER_ERROR,
    HTTP_NOT_FOUND,
    HTTP_UNPROCESSABLE_ENTITY,
)
from .loops.errors import (
    CloopError,
    DependencyCycleError,
    DependencyNotMetError,
    NotFoundError,
    TransitionError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def _http_error(detail: Any, *, status_code: int, error_type: str) -> JSONResponse:
    """Build a structured JSON error response."""
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail") or "Request failed"
        details = detail
    else:
        message = str(detail)
        details = {}
    return JSONResponse(
        status_code=status_code,
        content={"error": {"type": error_type, "message": message, "details": details}},
    )


def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException."""
    return _http_error(exc.detail, status_code=exc.status_code, error_type="http_error")


def handle_cloop_error(_: Request, exc: CloopError) -> JSONResponse:
    """Handle all typed Cloop domain exceptions.

    Maps exception types to appropriate HTTP status codes:
    - NotFoundError -> 404
    - ValidationError -> 400
    - TransitionError -> 400
    - Other CloopError -> 400
    """
    if isinstance(exc, NotFoundError):
        status_code = HTTP_NOT_FOUND
        error_type = "not_found"
    elif isinstance(exc, TransitionError):
        status_code = HTTP_BAD_REQUEST
        error_type = "transition_error"
    elif isinstance(exc, ValidationError):
        status_code = HTTP_BAD_REQUEST
        error_type = "validation_error"
    elif isinstance(exc, DependencyCycleError):
        status_code = HTTP_BAD_REQUEST
        error_type = "dependency_cycle"
    elif isinstance(exc, DependencyNotMetError):
        status_code = HTTP_BAD_REQUEST
        error_type = "dependency_not_met"
        # Include open_dependencies in the response
        return _http_error(
            {
                "message": exc.message,
                "detail": exc.detail,
                "open_dependencies": exc.open_dependencies,
            },
            status_code=status_code,
            error_type=error_type,
        )
    else:
        status_code = HTTP_BAD_REQUEST
        error_type = "domain_error"

    return _http_error(
        {"message": exc.message, "detail": exc.detail},
        status_code=status_code,
        error_type=error_type,
    )


def handle_validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic request validation errors."""
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
    return _http_error(
        {"message": "Validation failed", "errors": serialized_errors},
        status_code=HTTP_UNPROCESSABLE_ENTITY,
        error_type="validation_error",
    )


def handle_generic_exception(_: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with sanitized response.

    Full exception details are logged server-side with a unique error_id
    for correlation. Clients receive only the error_id, not internal details.
    """
    error_id = str(uuid.uuid4())
    logger.exception("Unhandled exception [%s]: %s", error_id, exc)
    return _http_error(
        {"message": "Unexpected server error", "error_id": error_id},
        status_code=HTTP_INTERNAL_SERVER_ERROR,
        error_type="server_error",
    )


def register_exception_handlers(app) -> None:
    """Register all exception handlers with a FastAPI app.

    Usage:
        app = FastAPI(...)
        register_exception_handlers(app)
    """
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(CloopError, handle_cloop_error)
    app.add_exception_handler(RequestValidationError, handle_validation_exception)
    app.add_exception_handler(Exception, handle_generic_exception)
