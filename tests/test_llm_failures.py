"""Tests for generative and embedding failure scenarios."""

from pathlib import Path

import litellm
import pytest

from cloop.ai_bridge.errors import (
    BridgeProtocolError,
    BridgeStartupError,
    BridgeTimeoutError,
    BridgeUpstreamError,
    ReadOnlyGenerationExhaustedError,
)


@pytest.mark.parametrize(
    ("exc", "status_code", "error_type", "error_code"),
    [
        (
            BridgeStartupError("bridge unavailable"),
            503,
            "ai_backend_unavailable",
            "ai_backend_unavailable",
        ),
        (
            BridgeTimeoutError("bridge timed out"),
            504,
            "ai_backend_timeout",
            "ai_backend_timeout",
        ),
        (
            BridgeProtocolError("bridge protocol mismatch"),
            502,
            "ai_backend_protocol_error",
            "ai_backend_protocol_error",
        ),
    ],
)
def test_chat_bridge_failures_use_typed_error_contract(
    exc: Exception,
    status_code: int,
    error_type: str,
    error_code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_test_client,
) -> None:
    client = make_test_client(raise_server_exceptions=False)

    def mock_failure(*args, **kwargs):
        raise exc

    monkeypatch.setattr("cloop.chat_execution.chat_completion", mock_failure)

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
    )
    assert response.status_code == status_code
    data = response.json()
    assert data["error"]["type"] == error_type
    assert data["error"]["code"] == error_code
    assert data["error"]["message"] == str(exc)


def test_chat_untyped_runtime_error_returns_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client(raise_server_exceptions=False)

    def mock_failure(*args, **kwargs):
        raise RuntimeError("unexpected bridge wrapper failure")

    monkeypatch.setattr("cloop.chat_execution.chat_completion", mock_failure)

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
    )
    assert response.status_code == 500
    data = response.json()
    assert data["error"]["type"] == "server_error"


def test_chat_tool_round_limit_preserves_structured_error_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client(raise_server_exceptions=False)

    def mock_failure(*args, **kwargs):
        raise BridgeUpstreamError(
            "tool_round_limit",
            "tool budget exceeded",
            details={
                "surface": "chat",
                "tool_rounds_used": 3,
                "max_tool_rounds": 2,
                "partial_results": {"text": "draft", "tool_calls": [], "tool_results": []},
                "guidance": {"summary": "chat exhausted its tool-round budget (2)."},
            },
        )

    monkeypatch.setattr("cloop.chat_execution.chat_completion", mock_failure)

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
    )
    assert response.status_code == 502
    data = response.json()
    assert data["error"]["code"] == "tool_round_limit"
    assert data["error"]["details"]["surface"] == "chat"
    assert data["error"]["details"]["tool_rounds_used"] == 3
    assert data["error"]["details"]["partial_results"]["text"] == "draft"
    assert data["error"]["details"]["guidance"]["summary"] == (
        "chat exhausted its tool-round budget (2)."
    )


def test_chat_readonly_exhausted_failure_maps_to_explicit_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client(raise_server_exceptions=False)

    def mock_failure(*args, **kwargs):
        raise ReadOnlyGenerationExhaustedError(
            surface="chat",
            exhaustion_reason="alternate_strategy_already_used",
            attempts=[
                {
                    "attempt": 1,
                    "strategy": "primary",
                    "success": False,
                    "resolved_selector": "zai/glm-5.2",
                    "error_code": "provider_timeout",
                    "retryable": True,
                },
                {
                    "attempt": 2,
                    "strategy": "fallback_selector",
                    "success": False,
                    "resolved_selector": "kimi-coding/kimi-for-coding",
                    "error_code": "provider_timeout",
                    "retryable": True,
                },
            ],
            final_error=BridgeUpstreamError("provider_timeout", "timeout", retryable=True),
        )

    monkeypatch.setattr("cloop.chat_execution.chat_completion", mock_failure)

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
    )
    assert response.status_code == 503
    data = response.json()
    assert data["error"]["code"] == "readonly_generation_exhausted"
    assert data["error"]["details"]["surface"] == "chat"
    assert data["error"]["details"]["exhaustion_reason"] == "alternate_strategy_already_used"
    assert len(data["error"]["details"]["attempts"]) == 2
    assert data["error"]["details"]["final_error"]["code"] == "provider_timeout"


def test_ask_readonly_exhausted_failure_uses_shared_error_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client(raise_server_exceptions=False)

    def mock_failure(*args, **kwargs):
        raise ReadOnlyGenerationExhaustedError(
            surface="rag",
            exhaustion_reason="fallback_selector",
            attempts=[{"attempt": 1, "strategy": "primary", "success": False}],
            final_error=BridgeUpstreamError("provider_timeout", "timeout", retryable=True),
        )

    monkeypatch.setattr("cloop.routes.rag.execute_ask_request", mock_failure)

    response = client.get("/ask", params={"q": "hello"})
    assert response.status_code == 503
    data = response.json()
    assert data["error"]["code"] == "readonly_generation_exhausted"
    assert data["error"]["details"]["surface"] == "rag"


def test_embedding_timeout_during_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client(raise_server_exceptions=False)

    doc = tmp_path / "test.txt"
    doc.write_text("Test document content", encoding="utf-8")

    def mock_timeout(*args, **kwargs):
        raise litellm.Timeout(
            message="Embedding timed out", model="test-model", llm_provider="openai"
        )

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_timeout)

    response = client.post("/ingest", json={"paths": [str(doc)]})
    assert response.status_code == 500


def test_embedding_timeout_during_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    client = make_test_client(raise_server_exceptions=False)

    def mock_timeout(*args, **kwargs):
        raise litellm.Timeout(
            message="Embedding timed out", model="test-model", llm_provider="openai"
        )

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_timeout)

    response = client.get("/ask", params={"q": "test query"})
    assert response.status_code == 500
