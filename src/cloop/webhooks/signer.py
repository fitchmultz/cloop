"""HMAC-SHA256 webhook signature generation and verification.

Purpose:
    Sign and verify webhook payloads using HMAC-SHA256.

Responsibilities:
    - Generate webhook signatures
    - Verify incoming webhook signatures

Non-scope:
    - Webhook delivery (see webhooks/service.py)
    - Secret storage (use settings/env vars)
"""

import hashlib
import hmac
import json
import time
from typing import Any

# 5 minutes in seconds for replay attack protection
REPLAY_TOLERANCE_SECONDS = 300


def generate_signature(payload: dict[str, Any], secret: str, timestamp: str) -> str:
    """Generate HMAC-SHA256 signature for webhook payload.

    Signature format: t=<timestamp>,v1=<hex_signature>

    Args:
        payload: Event payload dictionary
        secret: Webhook secret
        timestamp: Unix timestamp as string

    Returns:
        Signature string
    """
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signed_payload = f"{timestamp}.{payload_bytes.decode('utf-8')}".encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_signature(payload: dict[str, Any], secret: str, signature_header: str) -> bool:
    """Verify HMAC-SHA256 signature from webhook request.

    Includes replay attack protection by validating timestamp is within ±5 minutes.

    Args:
        payload: Event payload dictionary
        secret: Webhook secret
        signature_header: Signature header value

    Returns:
        True if signature is valid and not replayed
    """
    try:
        # Parse the signature header
        parts = signature_header.split(",")
        if len(parts) < 2:
            return False

        # Extract timestamp and signature with proper KeyError handling
        timestamp_part = parts[0]
        sig_part = parts[1]

        # Validate parts have the expected format (t= and v1= prefixes)
        if not timestamp_part.startswith("t=") or not sig_part.startswith("v1="):
            return False

        # Extract values after the '='
        timestamp_str = timestamp_part.split("=", 1)[1]

        # Validate timestamp is numeric
        timestamp = int(timestamp_str)

        # Replay protection: verify timestamp is within ±5 minutes of current time
        current_time = int(time.time())
        if abs(current_time - timestamp) > REPLAY_TOLERANCE_SECONDS:
            return False

        # Generate expected signature
        expected = generate_signature(payload, secret, timestamp_str)

        # Compare signatures using constant-time comparison
        return hmac.compare_digest(expected, signature_header)

    except (IndexError, ValueError, KeyError):
        return False
