"""Tests for the shared application error contract.

Purpose:
    Verify that canonical error mapping stays stable across domain, bridge, and
    HTTP exception sources.

Responsibilities:
    - Assert representative domain exceptions map to the expected error view
    - Assert bridge/runtime failures preserve retryability and status codes
    - Assert HTTPException payload normalization remains transport-friendly

Scope:
    - Unit coverage for `cloop.error_contract`

Usage:
    - Run with `uv run pytest tests/test_error_contract.py -q`

Invariants/Assumptions:
    - Canonical error codes remain stable for transport callers.
    - Error response envelopes always include the canonical `code` in details.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from cloop.ai_bridge.errors import BridgeProtocolError, BridgeUpstreamError
from cloop.error_contract import error_response, error_view_from_exception
from cloop.loops.errors import CloopError, LoopClaimedError, ResourceNotFoundError


class TestErrorViewFromException:
    """Representative mapping coverage for the canonical error view builder."""

    def test_maps_loop_claim_conflict(self) -> None:
        """Loop claim conflicts should retain claim metadata and 409 semantics."""
        exc = LoopClaimedError(loop_id=7, owner="agent-alpha", lease_until="2026-03-15T10:00:00Z")

        view = error_view_from_exception(exc)

        assert view.error_type == "loop_claimed"
        assert view.code == "loop_claimed"
        assert view.message == exc.message
        assert view.details == {
            "loop_id": 7,
            "owner": "agent-alpha",
            "lease_until": "2026-03-15T10:00:00Z",
        }
        assert view.status_code == 409

    def test_maps_named_resource_not_found(self) -> None:
        """Named resources should get resource-specific not-found codes."""
        exc = ResourceNotFoundError("review_session")

        view = error_view_from_exception(exc)

        assert view.error_type == "not_found"
        assert view.code == "review_session_not_found"
        assert view.details["resource_type"] == "review_session"
        assert view.status_code == 404

    @pytest.mark.parametrize(
        ("retryable", "expected_status"),
        [(False, 502), (True, 503)],
    )
    def test_maps_bridge_upstream_errors(self, retryable: bool, expected_status: int) -> None:
        """Bridge upstream retryability should control the returned status code."""
        exc = BridgeUpstreamError("provider_failure", "provider exploded", retryable=retryable)

        view = error_view_from_exception(exc)

        assert view.error_type == "ai_backend_error"
        assert view.code == "provider_failure"
        assert view.details == {"detail": "provider exploded", "retryable": retryable}
        assert view.status_code == expected_status

    def test_maps_http_exception_detail_dict(self) -> None:
        """HTTPException dict payloads should preserve explicit message and code."""
        exc = HTTPException(
            status_code=422,
            detail={"code": "bad_widget", "message": "Widget invalid", "field": "widget_id"},
        )

        view = error_view_from_exception(exc)

        assert view.error_type == "http_error"
        assert view.code == "bad_widget"
        assert view.message == "Widget invalid"
        assert view.details == {
            "code": "bad_widget",
            "message": "Widget invalid",
            "field": "widget_id",
        }
        assert view.status_code == 422

    def test_maps_http_exception_scalar_detail(self) -> None:
        """Scalar HTTPException payloads should fall back to the generic HTTP code."""
        exc = HTTPException(status_code=418, detail="short and stout")

        view = error_view_from_exception(exc)

        assert view.error_type == "http_error"
        assert view.code == "http_error"
        assert view.message == "short and stout"
        assert view.details == {"detail": "short and stout"}
        assert view.status_code == 418

    def test_maps_generic_domain_error(self) -> None:
        """Unhandled CloopError subclasses should still use the generic domain contract."""
        exc = CloopError("domain exploded", detail="extra=1")

        view = error_view_from_exception(exc)

        assert view.error_type == "domain_error"
        assert view.code == "domain_error"
        assert view.details == {"detail": "extra=1"}
        assert view.status_code == 400

    def test_rejects_unsupported_exception_types(self) -> None:
        """Unsupported exceptions should fail fast instead of guessing a contract."""
        with pytest.raises(TypeError, match="unsupported_error_view:ValueError"):
            error_view_from_exception(ValueError("boom"))


class TestErrorResponse:
    """HTTP envelope coverage for canonical error response rendering."""

    def test_error_response_includes_code_inside_details(self) -> None:
        """Rendered error envelopes should duplicate the canonical code in details."""
        view = error_view_from_exception(BridgeProtocolError("protocol mismatch"))

        response = error_response(view)
        raw_body = bytes(response.body)
        payload = json.loads(raw_body)

        assert payload == {
            "error": {
                "type": "ai_backend_protocol_error",
                "code": "ai_backend_protocol_error",
                "message": "protocol mismatch",
                "details": {
                    "code": "ai_backend_protocol_error",
                    "detail": "protocol mismatch",
                },
            }
        }
        assert response.status_code == 502
