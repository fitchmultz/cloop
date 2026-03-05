# =============================================================================
# Loop Claim Tests
# =============================================================================
#
# Purpose:
#     Test the loop claim/locking mechanism for concurrent access control.
#
# Responsibilities:
#     - Verify claim acquisition, renewal, and release behavior
#     - Test claim token validation for protected operations
#     - Validate claim expiration and lazy cleanup
#     - Test idempotency and admin force-release
#
# Non-scope:
#     - General loop CRUD operations (see test_loop_capture.py)
#     - Loop enrichment or prioritization (see test_loop_enrichment.py, test_loop_prioritization.py)
#     - RAG or document handling
#
# Invariants:
#     - All tests use isolated test clients via make_test_client fixture
#     - Datetime helpers from conftest import _now_iso
# =============================================================================

import time
from pathlib import Path

import pytest
from conftest import _now_iso


def test_loop_claim_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Successfully claim an unclaimed loop."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim the loop
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 200
    claim = claim_response.json()
    assert claim["loop_id"] == loop_id
    assert claim["owner"] == "agent-1"
    assert "claim_token" in claim
    assert len(claim["claim_token"]) == 64  # 32 bytes = 64 hex chars


def test_loop_claim_already_claimed_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot claim a loop already claimed by another agent."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim the loop with agent-1
    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to claim with agent-2
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 409
    error = claim_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"
    assert error["error"]["details"]["owner"] == "agent-1"


def test_loop_update_claimed_without_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot update a claimed loop without the claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to update without token
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title"},
    )
    assert update_response.status_code == 409
    error = update_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"


def test_loop_update_claimed_with_valid_token_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can update a claimed loop with valid claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Update with token
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title", "claim_token": claim_token},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "New title"


def test_loop_update_claimed_with_invalid_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot update with wrong claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to update with wrong token
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title", "claim_token": "wrong_token_1234567890123456"},
    )
    assert update_response.status_code == 403
    error = update_response.json()
    assert error["error"]["details"]["code"] == "invalid_claim_token"


def test_loop_unclaimed_allows_update_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Unclaimed loops can be updated without token."""
    client = make_test_client()

    # Create a loop (not claimed)
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Update without token should work
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "New title"


def test_loop_renew_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can renew an existing claim."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 60},
    )
    claim_token = claim_response.json()["claim_token"]

    # Renew the claim
    renew_response = client.post(
        f"/loops/{loop_id}/renew",
        json={"claim_token": claim_token, "ttl_seconds": 300},
    )
    assert renew_response.status_code == 200
    renewed = renew_response.json()
    assert renewed["claim_token"] == claim_token
    assert renewed["owner"] == "agent-1"


def test_loop_release_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """After releasing, another agent can claim."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Release the claim
    release_response = client.request(
        "DELETE",
        f"/loops/{loop_id}/claim",
        json={"claim_token": claim_token},
    )
    assert release_response.status_code == 200
    assert release_response.json()["ok"] is True

    # Another agent can now claim
    claim2_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim2_response.status_code == 200
    assert claim2_response.json()["owner"] == "agent-2"


def test_loop_get_claim_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Get claim status returns claim info without token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Get claim status
    status_response = client.get(f"/loops/{loop_id}/claim")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["loop_id"] == loop_id
    assert status["owner"] == "agent-1"
    assert "claim_token" not in status  # Token should NOT be exposed


def test_loop_get_claim_status_unclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Get claim status returns null for unclaimed loop."""
    client = make_test_client()

    # Create a loop (not claimed)
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Get claim status
    status_response = client.get(f"/loops/{loop_id}/claim")
    assert status_response.status_code == 200
    assert status_response.json() is None


def test_loop_list_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """List active claims."""
    client = make_test_client()

    # Create and claim two loops
    create1 = client.post(
        "/loops/capture",
        json={"raw_text": "loop 1", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    loop_id_1 = create1.json()["id"]

    create2 = client.post(
        "/loops/capture",
        json={"raw_text": "loop 2", "captured_at": _now_iso(), "client_tz_offset_min": 0},
    )
    loop_id_2 = create2.json()["id"]

    client.post(f"/loops/{loop_id_1}/claim", json={"owner": "agent-alpha", "ttl_seconds": 300})
    client.post(f"/loops/{loop_id_2}/claim", json={"owner": "agent-beta", "ttl_seconds": 300})

    # List all claims
    list_response = client.get("/loops/claims")
    assert list_response.status_code == 200
    claims = list_response.json()
    assert len(claims) == 2

    # Filter by owner
    alpha_response = client.get("/loops/claims?owner=agent-alpha")
    assert alpha_response.status_code == 200
    alpha_claims = alpha_response.json()
    assert len(alpha_claims) == 1
    assert alpha_claims[0]["owner"] == "agent-alpha"


def test_loop_force_release_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Force-release allows admin to unstick a loop."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Force-release without token
    force_response = client.delete(f"/loops/{loop_id}/claim/force")
    assert force_response.status_code == 200
    assert force_response.json()["released"] is True

    # Verify loop can now be claimed by another
    claim2_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim2_response.status_code == 200


def test_loop_claim_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim operations return 404 for non-existent loop."""
    client = make_test_client()

    claim_response = client.post(
        "/loops/99999/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 404


def test_loop_claim_idempotency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim supports idempotency keys for replay protection."""
    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    headers = {"Idempotency-Key": "claim-key-1"}

    # First claim
    claim1 = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
        headers=headers,
    )
    assert claim1.status_code == 200
    token1 = claim1.json()["claim_token"]
    lease_until_1 = claim1.json()["lease_until_utc"]

    # Second claim with same idempotency key and same payload should return original
    claim2 = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
        headers=headers,
    )
    assert claim2.status_code == 200
    # Should be the replayed response with original token
    assert claim2.json()["claim_token"] == token1
    assert claim2.json()["lease_until_utc"] == lease_until_1


def test_settings_claim_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test claim settings validation."""
    from cloop.settings import get_settings

    # Test invalid claim_default_ttl_seconds
    monkeypatch.setenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_CLAIM_DEFAULT_TTL_SECONDS must be at least 1"):
        get_settings()

    monkeypatch.delenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", raising=False)
    get_settings.cache_clear()

    # Test claim_max_ttl_seconds < claim_default_ttl_seconds
    monkeypatch.setenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", "3600")
    monkeypatch.setenv("CLOOP_CLAIM_MAX_TTL_SECONDS", "60")
    get_settings.cache_clear()
    with pytest.raises(
        ValueError, match="CLOOP_CLAIM_MAX_TTL_SECONDS must be >= CLOOP_CLAIM_DEFAULT_TTL_SECONDS"
    ):
        get_settings()

    monkeypatch.delenv("CLOOP_CLAIM_DEFAULT_TTL_SECONDS", raising=False)
    monkeypatch.delenv("CLOOP_CLAIM_MAX_TTL_SECONDS", raising=False)
    get_settings.cache_clear()

    # Test invalid claim_token_bytes
    monkeypatch.setenv("CLOOP_CLAIM_TOKEN_BYTES", "8")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="CLOOP_CLAIM_TOKEN_BYTES must be at least 16"):
        get_settings()

    monkeypatch.delenv("CLOOP_CLAIM_TOKEN_BYTES", raising=False)
    get_settings.cache_clear()


@pytest.mark.slow
def test_loop_claim_expired_allows_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Expired claims allow updates without token (lazy expiration check)."""
    client = make_test_client()

    # Create and claim a loop with short TTL
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim with 1 second TTL (minimum allowed)
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 1},
    )
    assert claim_response.status_code == 200

    # Wait for claim to expire
    time.sleep(1.5)

    # Update should work without token (claim expired)
    update_response = client.patch(
        f"/loops/{loop_id}",
        json={"title": "New title"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "New title"


@pytest.mark.slow
def test_loop_claim_expired_allows_new_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """After claim expires, another agent can claim it."""
    client = make_test_client()

    # Create and claim a loop with short TTL
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim with 1 second TTL
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 1},
    )
    assert claim_response.status_code == 200

    # Wait for claim to expire
    time.sleep(1.5)

    # Another agent can now claim (expired claims are purged on new claim attempt)
    claim2_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-2", "ttl_seconds": 300},
    )
    assert claim2_response.status_code == 200
    assert claim2_response.json()["owner"] == "agent-2"


def test_loop_claim_token_length_uses_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim token length respects claim_token_bytes setting."""
    # Set custom token length
    monkeypatch.setenv("CLOOP_CLAIM_TOKEN_BYTES", "64")
    from cloop.settings import get_settings

    get_settings.cache_clear()

    client = make_test_client()

    # Create a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Claim the loop
    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    assert claim_response.status_code == 200
    claim_token = claim_response.json()["claim_token"]

    # Token should be 128 hex characters (64 bytes = 128 hex chars)
    assert len(claim_token) == 128

    # Cleanup
    monkeypatch.delenv("CLOOP_CLAIM_TOKEN_BYTES", raising=False)
    get_settings.cache_clear()


def test_loop_close_claimed_with_valid_token_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can close a claimed loop with valid claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Close with token
    close_response = client.post(
        f"/loops/{loop_id}/close",
        json={"status": "completed", "claim_token": claim_token},
    )
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "completed"


def test_loop_close_claimed_without_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot close a claimed loop without the claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to close without token
    close_response = client.post(
        f"/loops/{loop_id}/close",
        json={"status": "completed"},
    )
    assert close_response.status_code == 409
    error = close_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"


def test_loop_status_claimed_with_valid_token_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Can transition status of a claimed loop with valid claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    claim_response = client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )
    claim_token = claim_response.json()["claim_token"]

    # Transition status with token
    status_response = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "actionable", "claim_token": claim_token},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "actionable"


def test_loop_status_claimed_without_token_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Cannot transition status of a claimed loop without the claim token."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # Try to transition without token
    status_response = client.post(
        f"/loops/{loop_id}/status",
        json={"status": "actionable"},
    )
    assert status_response.status_code == 409
    error = status_response.json()
    assert error["error"]["details"]["code"] == "loop_claimed"


def test_loop_claim_token_not_exposed_in_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Claim tokens should not be exposed in list_active_claims response."""
    client = make_test_client()

    # Create and claim a loop
    create_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "test loop",
            "captured_at": _now_iso(),
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    client.post(
        f"/loops/{loop_id}/claim",
        json={"owner": "agent-1", "ttl_seconds": 300},
    )

    # List claims
    list_response = client.get("/loops/claims")
    assert list_response.status_code == 200
    claims = list_response.json()
    assert len(claims) == 1

    # Token should NOT be exposed
    assert "claim_token" not in claims[0]
    assert claims[0]["owner"] == "agent-1"
    assert claims[0]["loop_id"] == loop_id
