"""Shared orchestration for idempotent HTTP routes and MCP tools.

Purpose:
    Centralize the prepare/replay/finalize flow used by write operations that
    support idempotent retries.

Responsibilities:
    - Normalize request identifiers and build replay scopes
    - Claim or replay idempotent operations against the database
    - Expose route- and MCP-friendly helpers for replay handling
    - Finalize stored responses after successful mutations

Non-scope:
    - Does not define idempotency hashing primitives or scope builders
    - Does not implement business mutations
    - Does not serialize domain models into HTTP or MCP response payloads
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from mcp.server.fastmcp.exceptions import ToolError

from .idempotency import (
    IdempotencyConflictError,
    build_http_scope,
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from .settings import Settings
from .storage import idempotency_store


@dataclass(frozen=True)
class PreparedIdempotentRequest:
    """Prepared idempotent request state for a single mutation."""

    scope: str
    key: str | None
    replay_status_code: int | None = None
    replay_body: Any | None = None

    @property
    def has_replay(self) -> bool:
        """Return True when the request should short-circuit to a stored replay."""
        return self.replay_body is not None and self.replay_status_code is not None


def prepare_http_idempotency(
    *,
    method: str,
    path: str,
    idempotency_key: str | None,
    payload: Mapping[str, Any],
    settings: Settings,
    conn: Any,
) -> PreparedIdempotentRequest:
    """Prepare idempotency state for an HTTP mutation request."""
    return _prepare_idempotency(
        scope=build_http_scope(method, path),
        request_id=idempotency_key,
        payload=payload,
        settings=settings,
        conn=conn,
        invalid_key_error=lambda message: HTTPException(status_code=400, detail=message),
        conflict_error=lambda message: HTTPException(
            status_code=409,
            detail={"message": "idempotency_key_conflict", "detail": message},
        ),
    )


def prepare_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: Mapping[str, Any],
    settings: Settings,
    conn: Any,
) -> PreparedIdempotentRequest:
    """Prepare idempotency state for an MCP tool call."""
    return _prepare_idempotency(
        scope=build_mcp_scope(tool_name),
        request_id=request_id,
        payload=payload,
        settings=settings,
        conn=conn,
        invalid_key_error=ToolError,
        conflict_error=lambda message: ToolError(f"Idempotency conflict: {message}"),
    )


def replay_http_response(state: PreparedIdempotentRequest) -> JSONResponse | None:
    """Return a JSON replay response when the prepared state contains one."""
    if not state.has_replay:
        return None
    status_code = state.replay_status_code
    assert status_code is not None
    return JSONResponse(content=state.replay_body, status_code=status_code)


def replay_mcp_response(state: PreparedIdempotentRequest) -> Any | None:
    """Return the replay body for an MCP tool call, if present."""
    if not state.has_replay:
        return None
    return state.replay_body


def finalize_idempotent_response(
    *,
    state: PreparedIdempotentRequest,
    response_status: int,
    response_body: Any,
    conn: Any,
) -> None:
    """Persist the response body for a prepared idempotent request."""
    if state.key is None:
        return

    idempotency_store.finalize_idempotency_response(
        scope=state.scope,
        idempotency_key=state.key,
        response_status=response_status,
        response_body=response_body,
        conn=conn,
    )


def _prepare_idempotency(
    *,
    scope: str,
    request_id: str | None,
    payload: Mapping[str, Any],
    settings: Settings,
    conn: Any,
    invalid_key_error: Any,
    conflict_error: Any,
) -> PreparedIdempotentRequest:
    """Claim or replay an idempotent mutation request."""
    if request_id is None:
        return PreparedIdempotentRequest(scope=scope, key=None)

    try:
        key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    except ValueError as exc:
        raise invalid_key_error(str(exc)) from None

    try:
        claim = idempotency_store.claim_or_replay_idempotency(
            scope=scope,
            idempotency_key=key,
            request_hash=canonical_request_hash(payload),
            expires_at=expiry_timestamp(settings.idempotency_ttl_seconds),
            conn=conn,
        )
    except IdempotencyConflictError as exc:
        raise conflict_error(str(exc)) from None

    replay = claim.get("replay")
    if claim["is_new"] or replay is None:
        return PreparedIdempotentRequest(scope=scope, key=key)

    return PreparedIdempotentRequest(
        scope=scope,
        key=key,
        replay_status_code=replay["status_code"],
        replay_body=replay["response_body"],
    )
