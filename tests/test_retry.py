"""Tests for retry logic in LLM and embedding API calls.

Purpose:
    Verify retry behavior for transient errors and no-retry for permanent errors.

Non-scope:
    Testing actual LLM provider behavior (assume litellm works).
"""

from pathlib import Path
from typing import Any, Dict

import litellm
import pytest

from cloop.embeddings import embed_texts
from cloop.llm import chat_completion
from cloop.settings import get_settings


def _configure_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> None:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


class TestRetriableErrors:
    """Tests that retriable errors trigger retries before final failure."""

    def test_timeout_triggers_retry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that Timeout errors are retried."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_LLM_MODEL="mock-llm",
            CLOOP_LLM_MAX_RETRIES="2",
        )

        attempt_count = 0

        def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:  # Fail first 2 attempts
                raise litellm.Timeout(
                    message="Request timed out", model="mock-llm", llm_provider="test"
                )
            return {"choices": [{"message": {"content": "success"}}], "model": "mock-llm"}

        monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

        result, _ = chat_completion([{"role": "user", "content": "test"}], settings=get_settings())
        assert result == "success"
        assert attempt_count == 3  # Initial + 2 retries

    def test_rate_limit_triggers_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that RateLimitError is retried."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_LLM_MODEL="mock-llm",
            CLOOP_LLM_MAX_RETRIES="2",
        )

        attempt_count = 0

        def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise litellm.RateLimitError(
                    message="Rate limited", model="mock-llm", llm_provider="test"
                )
            return {"choices": [{"message": {"content": "ok"}}], "model": "mock-llm"}

        monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

        result, _ = chat_completion([{"role": "user", "content": "test"}], settings=get_settings())
        assert result == "ok"
        assert attempt_count == 2

    def test_connection_error_triggers_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that APIConnectionError is retried."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_LLM_MODEL="mock-llm",
            CLOOP_LLM_MAX_RETRIES="1",
        )

        attempt_count = 0

        def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise litellm.APIConnectionError(
                    message="Connection failed", model="mock-llm", llm_provider="test"
                )
            return {"choices": [{"message": {"content": "recovered"}}], "model": "mock-llm"}

        monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

        result, _ = chat_completion([{"role": "user", "content": "test"}], settings=get_settings())
        assert result == "recovered"

    def test_embedding_timeout_triggers_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that embedding Timeout errors are retried."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_EMBED_MODEL="mock-embed",
            CLOOP_LLM_MAX_RETRIES="2",
        )

        attempt_count = 0

        def fake_embedding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise litellm.Timeout(
                    message="Embedding timeout", model="mock-embed", llm_provider="test"
                )
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

        monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

        vectors = embed_texts(["test"], settings=get_settings())
        assert len(vectors) == 1
        assert attempt_count == 2


class TestNonRetriableErrors:
    """Tests that non-retriable errors fail immediately without retry."""

    def test_authentication_error_no_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that AuthenticationError is NOT retried."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_LLM_MODEL="mock-llm",
            CLOOP_LLM_MAX_RETRIES="3",
        )

        attempt_count = 0

        def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            raise litellm.AuthenticationError(
                message="Invalid API key", model="mock-llm", llm_provider="test"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

        with pytest.raises(litellm.AuthenticationError):
            chat_completion([{"role": "user", "content": "test"}], settings=get_settings())

        assert attempt_count == 1  # No retries for auth errors

    def test_context_window_error_no_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that ContextWindowExceededError is NOT retried."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_LLM_MODEL="mock-llm",
            CLOOP_LLM_MAX_RETRIES="3",
        )

        attempt_count = 0

        def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            raise litellm.ContextWindowExceededError(
                message="Context too long", model="mock-llm", llm_provider="test"
            )

        monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

        with pytest.raises(litellm.ContextWindowExceededError):
            chat_completion([{"role": "user", "content": "test"}], settings=get_settings())

        assert attempt_count == 1  # No retries


class TestMaxRetriesZero:
    """Tests for max_retries=0 edge case (no retries)."""

    def test_max_retries_zero_no_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that max_retries=0 means no retries, only initial attempt."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_LLM_MODEL="mock-llm",
            CLOOP_LLM_MAX_RETRIES="0",
        )

        attempt_count = 0

        def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            raise litellm.Timeout(message="Timeout", model="mock-llm", llm_provider="test")

        monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

        with pytest.raises(litellm.Timeout):
            chat_completion([{"role": "user", "content": "test"}], settings=get_settings())

        # Only 1 attempt (initial) since max_retries=0
        assert attempt_count == 1


class TestMaxRetriesExhausted:
    """Tests that exhausting retries raises the final exception."""

    def test_max_retries_exhausted_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that after max retries, the final exception is raised."""
        _configure_env(
            monkeypatch,
            tmp_path,
            CLOOP_LLM_MODEL="mock-llm",
            CLOOP_LLM_MAX_RETRIES="2",
        )

        attempt_count = 0

        def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            nonlocal attempt_count
            attempt_count += 1
            raise litellm.Timeout(message="Always timeout", model="mock-llm", llm_provider="test")

        monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

        with pytest.raises(litellm.Timeout):
            chat_completion([{"role": "user", "content": "test"}], settings=get_settings())

        # Initial attempt + 2 retries = 3 total attempts
        assert attempt_count == 3
