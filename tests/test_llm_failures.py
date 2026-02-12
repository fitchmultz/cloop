"""Tests for LLM and embedding failure scenarios.

Purpose: Verify LLM/embedding error handling and response shapes.
Non-scope: Testing actual LLM provider behavior (assume litellm works).
Invariants: All unhandled LLM/embedding errors return 500 with sanitized error response.
"""

from pathlib import Path

import litellm
import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.main import app
from cloop.settings import get_settings


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create test client with isolated database."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return TestClient(app, raise_server_exceptions=False)


class TestLLMTimeoutErrors:
    """Tests for litellm.Timeout exceptions."""

    def test_chat_completion_timeout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that chat timeout returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_timeout(*args, **kwargs):
            raise litellm.Timeout(
                message="Request timed out", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", mock_timeout)

        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
        )
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "server_error"

    def test_embedding_timeout_during_ingest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that embedding timeout during ingest returns 500."""
        client = _make_client(tmp_path, monkeypatch)

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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that embedding timeout during RAG query returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_timeout(*args, **kwargs):
            raise litellm.Timeout(
                message="Embedding timed out", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_timeout)

        response = client.get("/ask", params={"q": "test query"})
        assert response.status_code == 500


class TestLLMConnectionErrors:
    """Tests for litellm.APIConnectionError exceptions."""

    def test_chat_connection_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that connection error returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_connection_error(*args, **kwargs):
            raise litellm.APIConnectionError(
                message="Failed to connect to API", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", mock_connection_error)

        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
        )
        assert response.status_code == 500

    def test_embedding_connection_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that embedding connection error returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_connection_error(*args, **kwargs):
            raise litellm.APIConnectionError(
                message="Failed to connect to embedding API",
                model="test-model",
                llm_provider="openai",
            )

        monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_connection_error)

        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
        )
        assert response.status_code == 500


class TestLLMRateLimitErrors:
    """Tests for litellm.RateLimitError exceptions."""

    def test_chat_rate_limit_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that rate limit error returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_rate_limit(*args, **kwargs):
            raise litellm.RateLimitError(
                message="Rate limit exceeded", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", mock_rate_limit)

        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
        )
        assert response.status_code == 500

    def test_embedding_rate_limit_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that embedding rate limit returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        doc = tmp_path / "test.txt"
        doc.write_text("Test document content", encoding="utf-8")

        def mock_rate_limit(*args, **kwargs):
            raise litellm.RateLimitError(
                message="Embedding rate limit exceeded", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_rate_limit)

        response = client.post("/ingest", json={"paths": [str(doc)]})
        assert response.status_code == 500


class TestLLMServiceUnavailableErrors:
    """Tests for litellm.ServiceUnavailableError exceptions."""

    def test_chat_service_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that service unavailable returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_unavailable(*args, **kwargs):
            raise litellm.ServiceUnavailableError(
                message="Service temporarily unavailable", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", mock_unavailable)

        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
        )
        assert response.status_code == 500


class TestLLMContextWindowErrors:
    """Tests for litellm.ContextWindowExceededError exceptions."""

    def test_chat_context_window_exceeded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that context window exceeded returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_context_exceeded(*args, **kwargs):
            raise litellm.ContextWindowExceededError(
                message="Context window exceeded", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", mock_context_exceeded)

        response = client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Very long message..."}],
                "tool_mode": "none",
            },
        )
        assert response.status_code == 500


class TestLLMAuthenticationErrors:
    """Tests for litellm.AuthenticationError exceptions."""

    def test_chat_invalid_api_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that auth error returns 500 (does not leak auth details)."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_auth_error(*args, **kwargs):
            raise litellm.AuthenticationError(
                message="Invalid API key", model="test-model", llm_provider="openai"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", mock_auth_error)

        response = client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"},
        )
        assert response.status_code == 500
        data = response.json()
        assert "API key" not in str(data)
