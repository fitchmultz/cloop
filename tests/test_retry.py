"""Tests for embeddings-only LiteLLM retry behavior."""

from pathlib import Path
from typing import Any

import litellm
import pytest

from cloop.embeddings import embed_texts
from cloop.settings import get_settings


def _configure_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> None:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_embedding_timeout_triggers_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="mock-embed",
        CLOOP_LLM_MAX_RETRIES="2",
    )

    attempt_count = 0

    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
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


def test_embedding_authentication_error_no_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="mock-embed",
        CLOOP_LLM_MAX_RETRIES="3",
    )

    attempt_count = 0

    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal attempt_count
        attempt_count += 1
        raise litellm.AuthenticationError(
            message="Invalid API key", model="mock-embed", llm_provider="test"
        )

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    with pytest.raises(litellm.AuthenticationError):
        embed_texts(["test"], settings=get_settings())

    assert attempt_count == 1


def test_embedding_max_retries_exhausted_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="mock-embed",
        CLOOP_LLM_MAX_RETRIES="2",
    )

    attempt_count = 0

    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal attempt_count
        attempt_count += 1
        raise litellm.Timeout(message="Always timeout", model="mock-embed", llm_provider="test")

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    with pytest.raises(litellm.Timeout):
        embed_texts(["test"], settings=get_settings())

    assert attempt_count == 3
