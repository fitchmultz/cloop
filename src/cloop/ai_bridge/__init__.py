"""Pi bridge runtime for generative model calls.

Purpose:
    Provide the Python-side runtime boundary for the repo-owned pi bridge.

Responsibilities:
    - Expose bridge runtime accessors
    - Re-export bridge protocol constants and error types

Non-scope:
    - Route orchestration (see llm.py and routes/)
    - Embedding provider behavior (see embeddings.py)
"""

from .errors import (
    BridgeProcessError,
    BridgeProtocolError,
    BridgeStartupError,
    BridgeTimeoutError,
    BridgeUpstreamError,
)
from .protocol import PROTOCOL_VERSION
from .runtime import BridgeRuntime, bridge_health, get_bridge_runtime, shutdown_bridge_runtime

__all__ = [
    "BridgeProcessError",
    "BridgeProtocolError",
    "BridgeRuntime",
    "BridgeStartupError",
    "BridgeTimeoutError",
    "BridgeUpstreamError",
    "PROTOCOL_VERSION",
    "bridge_health",
    "get_bridge_runtime",
    "shutdown_bridge_runtime",
]
