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

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
