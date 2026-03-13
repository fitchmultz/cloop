"""Tests for generative and embedding failure scenarios."""

from pathlib import Path

import litellm
import pytest

from cloop.ai_bridge.errors import BridgeProtocolError, BridgeStartupError, BridgeTimeoutError


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

    monkeypatch.setattr("cloop.routes.chat.chat_completion", mock_failure)

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

    monkeypatch.setattr("cloop.routes.chat.chat_completion", mock_failure)

    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
    )
    assert response.status_code == 500
    data = response.json()
    assert data["error"]["type"] == "server_error"


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
