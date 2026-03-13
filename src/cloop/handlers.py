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

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .ai_bridge.errors import BridgeError
from .error_contract import (
    error_response,
    error_view_from_exception,
    internal_error_view,
    request_validation_error_view,
)
from .loops.errors import CloopError

logger = logging.getLogger(__name__)


def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException."""
    return error_response(error_view_from_exception(exc))


def handle_cloop_error(_: Request, exc: CloopError) -> JSONResponse:
    """Handle all typed Cloop domain exceptions through the shared contract."""
    return error_response(error_view_from_exception(exc))


def handle_bridge_error(_: Request, exc: BridgeError) -> JSONResponse:
    """Handle bridge/runtime failures through the shared error contract."""
    return error_response(error_view_from_exception(exc))


def handle_validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic request validation errors."""
    return error_response(request_validation_error_view(exc))


def handle_generic_exception(_: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with sanitized response.

    Full exception details are logged server-side with a unique error_id
    for correlation. Clients receive only the error_id, not internal details.
    """
    error_id = str(uuid.uuid4())
    logger.exception("Unhandled exception [%s]: %s", error_id, exc)
    return error_response(internal_error_view(error_id=error_id))


def register_exception_handlers(app) -> None:
    """Register all exception handlers with a FastAPI app.

    Usage:
        app = FastAPI(...)
        register_exception_handlers(app)
    """
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(CloopError, handle_cloop_error)
    app.add_exception_handler(BridgeError, handle_bridge_error)
    app.add_exception_handler(RequestValidationError, handle_validation_exception)
    app.add_exception_handler(Exception, handle_generic_exception)
