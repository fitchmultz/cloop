"""HMAC-SHA256 webhook byte-signing.

Purpose:
    Sign and verify webhook payloads using HMAC-SHA256.

Responsibilities:
    - Generate webhook signatures over exact bytes
    - Verify incoming webhook signatures over exact bytes

Non-scope:
    - Webhook delivery (see webhooks/service.py)
    - Secret storage (use settings/env vars)
"""

import hashlib
import hmac
import time

# 5 minutes in seconds for replay attack protection
REPLAY_TOLERANCE_SECONDS = 300


def sign_bytes(payload_bytes: bytes, secret: str, timestamp: str) -> str:
    """Generate HMAC-SHA256 signature for exact webhook bytes.

    Signature format: t=<timestamp>,v1=<hex_signature>

    Args:
        payload_bytes: Exact transmitted request bytes
        secret: Webhook secret
        timestamp: Unix timestamp as string

    Returns:
        Signature string
    """
    signed_payload = timestamp.encode("utf-8") + b"." + payload_bytes
    signature = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_signature(payload_bytes: bytes, secret: str, signature_header: str) -> bool:
    """Verify HMAC-SHA256 signature from exact webhook bytes.

    Includes replay attack protection by validating timestamp is within ±5 minutes.

    Args:
        payload_bytes: Exact transmitted request bytes
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
        expected = sign_bytes(payload_bytes, secret, timestamp_str)

        # Compare signatures using constant-time comparison
        return hmac.compare_digest(expected, signature_header)

    except IndexError, ValueError, KeyError:
        return False
