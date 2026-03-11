"""Webhook and SSE tests for the loops subsystem.

Purpose:
    Test webhook subscription CRUD, delivery queueing, signature verification,
    and SSE event streaming functionality.

Responsibilities:
    - Webhook subscription lifecycle (create, read, update, delete)
    - HMAC-SHA256 signature generation and verification with replay protection
    - Webhook delivery queueing and filtering by event type
    - SSE event formatting functions
    - Webhook settings validation

Non-scope:
    - Loop CRUD operations (see test_loop_capture.py)
    - RAG functionality (see test_rag.py)
    - MCP server tests (see test_mcp_server.py)

Invariants:
    - All tests use isolated temporary databases via make_test_client fixture
    - Signature verification includes replay protection via timestamp validation
"""

import socket
import sqlite3
import time
from pathlib import Path
from typing import cast

import pytest
from conftest import _now_iso

from cloop import db
from cloop.settings import get_settings

# =============================================================================
# SSE Event Stream tests
# =============================================================================


def test_loop_events_sse_endpoint_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test SSE stream endpoint exists (can't test infinite stream easily)."""
    # The SSE stream runs forever with a while True loop, so we just verify
    # the route exists and would return streaming content type by checking the route
    from cloop.routes.loops import router

    route_paths = [route.path for route in router.routes]  # type: ignore[misc]
    assert "/loops/events/stream" in route_paths


# =============================================================================
# Webhook tests
# =============================================================================


def test_webhook_subscription_crud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook subscription CRUD operations."""
    client = make_test_client()

    # Create subscription
    create_response = client.post(
        "/loops/webhooks/subscriptions",
        json={
            "url": "https://example.com/webhook",
            "event_types": ["capture", "update"],
            "description": "Test webhook",
        },
    )
    assert create_response.status_code == 200
    sub = create_response.json()
    assert sub["url"] == "https://example.com/webhook"
    assert sub["event_types"] == ["capture", "update"]
    assert sub["active"] is True
    assert sub["description"] == "Test webhook"
    subscription_id = sub["id"]

    # List subscriptions
    list_response = client.get("/loops/webhooks/subscriptions")
    assert list_response.status_code == 200
    subs = list_response.json()
    assert len(subs) == 1
    assert subs[0]["id"] == subscription_id

    # Update subscription
    update_response = client.patch(
        f"/loops/webhooks/subscriptions/{subscription_id}",
        json={
            "url": "https://example.com/webhook/v2",
            "active": False,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["url"] == "https://example.com/webhook/v2"
    assert updated["active"] is False

    # Delete subscription
    delete_response = client.delete(f"/loops/webhooks/subscriptions/{subscription_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    # Verify deletion
    list_after = client.get("/loops/webhooks/subscriptions")
    assert len(list_after.json()) == 0


def test_webhook_subscription_url_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook subscription URL validation."""
    client = make_test_client()

    # Invalid URL without http/https
    response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "ftp://example.com/webhook"},
    )
    assert response.status_code == 422

    # Valid https URL
    response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "https://example.com/webhook"},
    )
    assert response.status_code == 200


def test_webhook_subscription_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook subscription endpoints return 404 for non-existent subscription."""
    client = make_test_client()

    # Update non-existent
    response = client.patch(
        "/loops/webhooks/subscriptions/99999",
        json={"active": False},
    )
    assert response.status_code == 404

    # Delete non-existent
    response = client.delete("/loops/webhooks/subscriptions/99999")
    assert response.status_code == 404

    # Get deliveries for non-existent
    response = client.get("/loops/webhooks/subscriptions/99999/deliveries")
    assert response.status_code == 404


def test_webhook_signature_generation_and_verification() -> None:
    """Test HMAC-SHA256 signature generation and verification."""
    from cloop.webhooks.service import _canonical_json_bytes
    from cloop.webhooks.signer import sign_bytes, verify_signature

    payload = {"loop_id": 123, "event_type": "capture"}
    payload_bytes = _canonical_json_bytes(payload)
    secret = "test_secret_key"
    timestamp = str(int(time.time()))  # Use current timestamp for replay protection

    # Generate signature
    signature = sign_bytes(payload_bytes, secret, timestamp)
    assert signature.startswith(f"t={timestamp},v1=")

    # Verify valid signature
    assert verify_signature(payload_bytes, secret, signature) is True

    # Verify with wrong secret
    assert verify_signature(payload_bytes, "wrong_secret", signature) is False

    # Verify with tampered payload
    tampered_payload = {"loop_id": 999, "event_type": "capture"}
    assert verify_signature(_canonical_json_bytes(tampered_payload), secret, signature) is False

    # Verify with invalid signature format
    assert verify_signature(payload_bytes, secret, "invalid-format") is False

    # Verify with expired timestamp (replay protection)
    old_timestamp = "1707830400"  # Old timestamp from 2024
    old_signature = sign_bytes(payload_bytes, secret, old_timestamp)
    assert verify_signature(payload_bytes, secret, old_signature) is False


def test_webhook_deliveries_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test listing deliveries for a webhook subscription."""
    client = make_test_client()

    # Create subscription
    sub_response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "https://example.com/webhook", "event_types": ["*"]},
    )
    subscription_id = sub_response.json()["id"]

    # Create a loop to trigger event creation (which queues webhook deliveries)
    client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )

    # List deliveries - should include the automatically queued delivery
    deliveries_response = client.get(f"/loops/webhooks/subscriptions/{subscription_id}/deliveries")
    assert deliveries_response.status_code == 200
    deliveries = deliveries_response.json()
    assert len(deliveries) == 1
    assert deliveries[0]["event_type"] == "capture"
    assert deliveries[0]["status"] == "queued"


def test_webhook_update_no_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook update with no fields returns 400."""
    client = make_test_client()

    # Create subscription
    sub_response = client.post(
        "/loops/webhooks/subscriptions",
        json={"url": "https://example.com/webhook"},
    )
    subscription_id = sub_response.json()["id"]

    # Update with empty body
    response = client.patch(f"/loops/webhooks/subscriptions/{subscription_id}", json={})
    assert response.status_code == 400
    assert "no_fields_to_update" in response.text


def test_webhook_event_type_filtering() -> None:
    """Test webhook event type filtering logic."""
    from cloop.webhooks.service import _should_deliver_event

    # Wildcard accepts all events
    assert _should_deliver_event("capture", ["*"]) is True
    assert _should_deliver_event("update", ["*"]) is True
    assert _should_deliver_event("close", ["*"]) is True

    # Specific event types
    assert _should_deliver_event("capture", ["capture", "update"]) is True
    assert _should_deliver_event("close", ["capture", "update"]) is False
    assert _should_deliver_event("update", ["update"]) is True

    # Empty list accepts nothing (except via wildcard)
    assert _should_deliver_event("capture", []) is False


def test_webhook_retry_delay_calculation(test_settings) -> None:
    """Test exponential backoff delay calculation."""
    from cloop.webhooks.service import _calculate_retry_delay

    settings = test_settings()

    # First retry should be around base delay (2s) +/- jitter
    delay0 = _calculate_retry_delay(0, settings)
    assert 1.0 <= delay0 <= 3.0  # 2s +/- 25%

    # Second retry should be around 4s +/- jitter
    delay1 = _calculate_retry_delay(1, settings)
    assert 3.0 <= delay1 <= 5.0  # 4s +/- 25%

    # Third retry should be around 8s +/- jitter
    delay2 = _calculate_retry_delay(2, settings)
    assert 6.0 <= delay2 <= 10.0  # 8s +/- 25%

    # High retry count should cap at max_delay
    delay_high = _calculate_retry_delay(100, settings)
    assert delay_high <= settings.webhook_retry_max_delay


def test_webhook_repo_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook repository operations directly."""
    from cloop.webhooks import repo
    from cloop.webhooks.models import DeliveryAttemptStatus, DeliveryStatus

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create subscription
    sub = repo.create_subscription(
        url="https://example.com/webhook",
        secret="test_secret",
        event_types=["capture", "update"],
        description="Test sub",
        conn=conn,
    )
    assert sub.url == "https://example.com/webhook"
    assert sub.event_types == ["capture", "update"]
    assert sub.active is True

    # Get subscription
    fetched = repo.get_subscription(subscription_id=sub.id, conn=conn)
    assert fetched is not None
    assert fetched.id == sub.id

    # Get non-existent
    not_found = repo.get_subscription(subscription_id=99999, conn=conn)
    assert not_found is None

    # List subscriptions
    subs = repo.list_subscriptions(conn=conn)
    assert len(subs) == 1

    # Update subscription
    updated = repo.update_subscription(
        subscription_id=sub.id,
        active=False,
        conn=conn,
    )
    assert updated is not None
    assert updated.active is False

    # Create delivery
    delivery = repo.create_delivery(
        subscription_id=sub.id,
        event_id=1,
        event_type="capture",
        payload={"test": "data"},
        conn=conn,
    )
    conn.commit()
    assert delivery.subscription_id == sub.id
    assert delivery.status == DeliveryStatus.QUEUED
    assert delivery.source_payload_json is not None

    # Claim and finalize one delivery attempt
    claimed = repo.claim_delivery_attempt(
        conn=conn,
        owner_token="worker-a",
        lease_seconds=60,
        delivery_id=delivery.id,
    )
    assert claimed is not None
    claimed_delivery, attempt = claimed
    repo.finalize_delivery_attempt(
        conn=conn,
        delivery_id=claimed_delivery.id,
        attempt_number=attempt.attempt_number,
        owner_token="worker-a",
        delivery_status=DeliveryStatus.SUCCEEDED,
        attempt_status=DeliveryAttemptStatus.SUCCEEDED,
        request_bytes=b'{"test":"data"}',
        signature_header="sig",
        started_at=attempt.started_at,
        finished_at=attempt.started_at,
        http_status=200,
        response_body="OK",
        error_message=None,
        connect_ip="203.0.113.10",
        next_retry_at_epoch=None,
    )

    # Get delivery
    fetched_delivery = repo.get_delivery(delivery_id=delivery.id, conn=conn)
    assert fetched_delivery is not None
    assert fetched_delivery.status == DeliveryStatus.SUCCEEDED
    assert fetched_delivery.http_status == 200

    # List deliveries for subscription
    deliveries = repo.list_deliveries_for_subscription(
        subscription_id=sub.id,
        conn=conn,
    )
    assert len(deliveries) == 1

    # Delete subscription
    deleted = repo.delete_subscription(subscription_id=sub.id, conn=conn)
    assert deleted is True

    # Verify deleted
    assert repo.get_subscription(subscription_id=sub.id, conn=conn) is None

    conn.close()


def test_webhook_queue_deliveries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test queueing webhook deliveries for events."""
    from cloop.webhooks import repo, service

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create subscriptions with different event types
    repo.create_subscription(
        url="https://example.com/all",
        secret="secret1",
        event_types=["*"],
        description="All events",
        conn=conn,
    )
    repo.create_subscription(
        url="https://example.com/capture-only",
        secret="secret2",
        event_types=["capture"],
        description="Capture only",
        conn=conn,
    )
    repo.create_subscription(
        url="https://example.com/inactive",
        secret="secret3",
        event_types=["*"],
        description="Inactive",
        conn=conn,
    )
    # Deactivate the third subscription
    conn.execute(
        "UPDATE webhook_subscriptions SET active = 0 WHERE url = ?",
        ("https://example.com/inactive",),
    )
    conn.commit()

    # Queue a capture event - should create deliveries for first two subscriptions
    delivery_ids = service.queue_deliveries(
        event_id=1,
        event_type="capture",
        payload={"test": "data"},
        conn=conn,
        settings=settings,
    )
    assert len(delivery_ids) == 2  # All events + capture-only

    # Queue an update event - should only create delivery for wildcard subscription
    delivery_ids = service.queue_deliveries(
        event_id=2,
        event_type="update",
        payload={"test": "data"},
        conn=conn,
        settings=settings,
    )
    assert len(delivery_ids) == 1  # Only all events subscription

    conn.close()


def test_webhook_delivery_signs_exact_transmitted_bytes(tmp_path: Path, monkeypatch) -> None:
    """Delivery should sign the exact canonical bytes sent on the wire."""
    from cloop.webhooks import repo, service
    from cloop.webhooks.signer import verify_signature

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    with conn:
        subscription = repo.create_subscription(
            url="https://example.com/webhook",
            secret="test-secret",
            event_types=["*"],
            description="Test sub",
            conn=conn,
        )
        conn.execute(
            """
            INSERT INTO loop_events (event_type, payload_json, created_at)
            VALUES ('capture', '{}', datetime('now'))
            """
        )
        delivery = repo.create_delivery(
            subscription_id=subscription.id,
            event_id=1,
            event_type="capture",
            payload={"loop_id": 42, "message": "hello"},
            conn=conn,
        )

    sent: dict[str, object] = {}

    def _fake_send(
        *,
        url: str,
        payload_bytes: bytes,
        headers: dict[str, str],
        timeout_seconds: float,
    ):
        sent["url"] = url
        sent["payload_bytes"] = payload_bytes
        sent["headers"] = headers
        sent["timeout_seconds"] = timeout_seconds
        return 200, "ok"

    monkeypatch.setattr(service, "_send_pinned_webhook_request", _fake_send)

    status = service.deliver_webhook(delivery_id=delivery.id, conn=conn, settings=settings)
    assert status.value == "succeeded"

    stored = repo.get_delivery(delivery_id=delivery.id, conn=conn)
    assert stored is not None
    payload_bytes = cast(bytes, sent["payload_bytes"])
    assert stored.last_attempt_payload_json == payload_bytes.decode("utf-8")
    assert verify_signature(
        payload_bytes,
        subscription.secret,
        stored.signature_header or "",
    )
    conn.close()


def test_webhook_reclaim_marks_stale_running_attempt_failed(tmp_path: Path, monkeypatch) -> None:
    """Expired in-flight deliveries should fail stale running attempts before reclaim."""
    from cloop.webhooks import repo

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row
    sub = repo.create_subscription(
        url="https://example.com/reclaim",
        secret="secret",
        event_types=["*"],
        description=None,
        conn=conn,
    )
    delivery = repo.create_delivery(
        subscription_id=sub.id,
        event_id=1,
        event_type="capture",
        payload={"ok": True},
        conn=conn,
    )
    conn.commit()

    claimed = repo.claim_delivery_attempt(
        conn=conn,
        owner_token="worker-a",
        lease_seconds=1,
        delivery_id=delivery.id,
    )
    assert claimed is not None
    conn.execute(
        "UPDATE webhook_deliveries SET lease_until_epoch = ? WHERE id = ?",
        (int(time.time()) - 5, delivery.id),
    )
    conn.commit()

    reclaimed = repo.claim_delivery_attempt(
        conn=conn,
        owner_token="worker-b",
        lease_seconds=60,
        delivery_id=delivery.id,
    )
    assert reclaimed is not None
    _, attempt = reclaimed
    attempts = repo.list_attempts_for_delivery(delivery_id=delivery.id, conn=conn)
    assert attempt.attempt_number == 2
    assert attempts[0].status == repo.DeliveryAttemptStatus.RUNNING
    assert attempts[1].status == repo.DeliveryAttemptStatus.FAILED
    assert attempts[1].error_message is not None
    assert "lease expired" in attempts[1].error_message.lower()
    conn.close()


def test_webhook_non_2xx_failure_preserves_http_observability(tmp_path: Path, monkeypatch) -> None:
    """Non-2xx webhook failures should persist status/body/connect IP for retries."""
    from cloop.webhooks import repo, service

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row
    sub = repo.create_subscription(
        url="https://example.com/failure",
        secret="secret",
        event_types=["*"],
        description=None,
        conn=conn,
    )
    delivery = repo.create_delivery(
        subscription_id=sub.id,
        event_id=1,
        event_type="capture",
        payload={"ok": False},
        conn=conn,
    )
    conn.commit()

    monkeypatch.setattr(
        service,
        "_send_pinned_webhook_request",
        lambda **kwargs: (500, "receiver said no", "203.0.113.10"),
    )
    monkeypatch.setattr(service.time, "time", lambda: 1_700_000_000)

    status = service.deliver_webhook(
        delivery_id=delivery.id,
        conn=conn,
        settings=settings,
        owner_token="worker-a",
    )
    attempts = repo.list_attempts_for_delivery(delivery_id=delivery.id, conn=conn)
    refreshed = repo.get_delivery(delivery_id=delivery.id, conn=conn)

    assert status == repo.DeliveryStatus.QUEUED
    assert refreshed is not None
    assert refreshed.status == repo.DeliveryStatus.QUEUED
    assert refreshed.http_status == 500
    assert refreshed.response_body == "receiver said no"
    assert refreshed.last_connect_ip == "203.0.113.10"
    assert refreshed.next_retry_at_epoch is not None
    assert attempts[0].http_status == 500
    assert attempts[0].response_body == "receiver said no"
    assert attempts[0].connect_ip == "203.0.113.10"
    conn.close()


def test_webhook_resolve_targets_accepts_safe_multi_ip(tmp_path: Path, monkeypatch) -> None:
    """Safe multi-IP targets should be accepted and deduplicated."""
    from cloop.webhooks.service import _resolve_safe_delivery_targets

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
        ],
    )

    ips, hostname, port, path = _resolve_safe_delivery_targets("https://example.com/hook?q=1")
    assert [str(ip) for ip in ips] == ["8.8.8.8", "1.1.1.1"]
    assert hostname == "example.com"
    assert port == 443
    assert path == "/hook?q=1"


def test_webhook_resolve_targets_rejects_private_ip(tmp_path: Path, monkeypatch) -> None:
    """Private resolved targets should be rejected before any outbound connect."""
    from cloop.webhooks.service import _resolve_safe_delivery_targets

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, type=0: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port)),
        ],
    )

    with pytest.raises(ValueError, match="Unsafe resolved address"):
        _resolve_safe_delivery_targets("https://example.com/hook")


def test_webhook_delivery_rejects_redirects(tmp_path: Path, monkeypatch) -> None:
    """Pinned webhook delivery should reject redirect responses."""
    from cloop.webhooks import service

    class _FakeResponse:
        status = 302

        def read(self) -> bytes:
            return b"redirect"

    class _FakeConnection:
        def __init__(self, *, hostname: str, connect_ip: str, port: int, timeout: float) -> None:
            self.closed = False

        def request(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
            return None

        def getresponse(self) -> _FakeResponse:
            return _FakeResponse()

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        service,
        "_resolve_safe_delivery_targets",
        lambda url: (("203.0.113.10",), "example.com", 443, "/hook"),
    )
    monkeypatch.setattr(service, "_PinnedHTTPSConnection", _FakeConnection)

    with pytest.raises(RuntimeError, match="Redirects are not allowed"):
        service._send_pinned_webhook_request(
            url="https://example.com/hook",
            payload_bytes=b"{}",
            headers={"Content-Type": "application/json"},
            timeout_seconds=5.0,
        )


def test_webhook_queueing_is_transaction_neutral(tmp_path: Path, monkeypatch) -> None:
    """Queueing deliveries should not commit the caller's outer transaction."""
    from cloop.webhooks import repo, service

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    with conn:
        repo.create_subscription(
            url="https://example.com/tx",
            secret="secret",
            event_types=["*"],
            description="tx",
            conn=conn,
        )

    conn.execute("BEGIN")
    conn.execute(
        """
        INSERT INTO loop_events (event_type, payload_json, created_at)
        VALUES ('capture', '{}', datetime('now'))
        """
    )
    service.queue_deliveries(
        event_id=1,
        event_type="capture",
        payload={"loop_id": 1},
        conn=conn,
        settings=settings,
    )
    conn.rollback()

    deliveries = conn.execute("SELECT COUNT(*) AS count FROM webhook_deliveries").fetchone()
    assert deliveries is not None
    assert deliveries["count"] == 0
    conn.close()


def test_sse_format_functions() -> None:
    """Test SSE formatting functions."""
    from cloop.sse import format_sse_comment, format_sse_event

    # Test event formatting
    event = format_sse_event("test_event", {"key": "value"}, event_id="123")
    assert "id: 123" in event
    assert "event: test_event" in event
    assert 'data: {"key": "value"}' in event
    assert event.endswith("\n\n")

    # Test event without ID
    event_no_id = format_sse_event("simple", {"data": True})
    assert "id:" not in event_no_id
    assert "event: simple" in event_no_id

    # Test comment formatting
    comment = format_sse_comment("heartbeat")
    assert comment == ": heartbeat\n\n"


def test_settings_webhook_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test webhook settings validation via environment variables."""
    from cloop.settings import get_settings

    # Test invalid webhook_max_retries
    monkeypatch.setenv("CLOOP_WEBHOOK_MAX_RETRIES", "-1")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_MAX_RETRIES must be non-negative"):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_MAX_RETRIES", raising=False)
    get_settings.cache_clear()

    # Test invalid webhook_retry_base_delay
    monkeypatch.setenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_RETRY_BASE_DELAY must be positive"):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", raising=False)
    get_settings.cache_clear()

    # Test invalid webhook_retry_max_delay < webhook_retry_base_delay
    monkeypatch.setenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", "10")
    monkeypatch.setenv("CLOOP_WEBHOOK_RETRY_MAX_DELAY", "1")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_RETRY_MAX_DELAY must be >="):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", raising=False)
    monkeypatch.delenv("CLOOP_WEBHOOK_RETRY_MAX_DELAY", raising=False)
    get_settings.cache_clear()

    # Test invalid webhook_timeout_seconds
    monkeypatch.setenv("CLOOP_WEBHOOK_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_WEBHOOK_TIMEOUT_SECONDS must be positive"):
        get_settings()

    # Reset
    monkeypatch.delenv("CLOOP_WEBHOOK_TIMEOUT_SECONDS", raising=False)
    get_settings.cache_clear()
