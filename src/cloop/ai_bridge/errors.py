"""Bridge-specific runtime errors.

Purpose:
    Give the pi bridge subsystem stable, explicit failure modes.

Responsibilities:
    - Distinguish startup/protocol/process/timeouts
    - Carry structured upstream error details when the bridge reports them

Non-scope:
    - HTTP error mapping (see handlers.py)
    - Tool-domain validation (see tools.py)
"""

from typing import Any


class BridgeError(RuntimeError):
    """Base class for bridge runtime failures."""


class BridgeStartupError(BridgeError):
    """Raised when the Node bridge cannot be started or handshaken."""


class BridgeProtocolError(BridgeError):
    """Raised when the JSONL protocol is violated."""


class BridgeProcessError(BridgeError):
    """Raised when the bridge process exits or becomes unusable."""


class BridgeTimeoutError(BridgeError):
    """Raised when startup or a request exceeds its configured timeout."""


class BridgeUpstreamError(BridgeError):
    """Raised when the bridge reports a model/provider failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


class ReadOnlyGenerationExhaustedError(BridgeUpstreamError):
    """Raised when a read-only request exhausts its bounded alternate strategy."""

    def __init__(
        self,
        *,
        surface: str,
        attempts: list[dict[str, Any]],
        final_error: BridgeUpstreamError,
        exhaustion_reason: str,
    ) -> None:
        final_error_payload = {
            "code": final_error.code,
            "message": str(final_error),
            "retryable": final_error.retryable,
            **final_error.details,
        }
        super().__init__(
            "readonly_generation_exhausted",
            f"Read-only generation exhausted bounded alternate strategies for {surface}",
            retryable=final_error.retryable,
            details={
                "surface": surface,
                "exhausted": True,
                "exhaustion_reason": exhaustion_reason,
                "attempts": attempts,
                "final_error": final_error_payload,
            },
        )
        self.attempts = attempts
        self.final_error = final_error
        self.exhaustion_reason = exhaustion_reason
