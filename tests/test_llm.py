from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

from cloop.embeddings import embed_texts
from cloop.llm import chat_completion
from cloop.settings import get_settings


def _configure_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> None:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_chat_completion_uses_ollama_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_LLM_MODEL="ollama/llama3",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    captured: Dict[str, Any] = {}

    def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        captured.update(kwargs)
        return {
            "choices": [{"message": {"content": "hi"}}],
            "model": kwargs.get("model", "ollama/llama3"),
            "usage": {},
        }

    monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

    chat_completion(
        [
            {"role": "user", "content": "Hello"},
        ],
        settings=get_settings(),
    )

    assert captured.get("api_base") == "http://localhost:11434/v1"


def test_chat_completion_uses_openai_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_LLM_MODEL="openai/gpt-4o-mini",
        CLOOP_OPENAI_API_BASE="https://custom.openai/v1",
        CLOOP_OPENAI_API_KEY="secret-key",
    )

    captured: Dict[str, Any] = {}

    def fake_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        captured.update(kwargs)
        return {
            "choices": [{"message": {"content": "hi"}}],
            "model": kwargs.get("model", "openai/gpt-4o-mini"),
            "usage": {},
        }

    monkeypatch.setattr("cloop.llm.litellm.completion", fake_completion)

    chat_completion(
        [
            {"role": "user", "content": "Hello"},
        ],
        settings=get_settings(),
    )

    assert captured.get("api_base") == "https://custom.openai/v1"
    assert captured.get("api_key") == "secret-key"


def test_embed_texts_forward_provider_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="ollama/nomic-embed-text",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    captured: Dict[str, Any] = {}

    def fake_embedding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        captured.update(kwargs)
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    vectors = embed_texts(["hello"], settings=get_settings())
    assert np.allclose(vectors[0], np.array([0.1, 0.2, 0.3], dtype=np.float32))
    assert captured.get("api_base") == "http://localhost:11434/v1"


def test_embed_texts_raises_on_malformed_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that embed_texts raises ValueError when embedding is not a list."""
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="ollama/nomic-embed-text",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    def fake_embedding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        # Return embedding as string instead of list (malformed response)
        return {"data": [{"embedding": "not-a-list"}]}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    with pytest.raises(ValueError, match="invalid_embedding_format"):
        embed_texts(["hello"], settings=get_settings())


def test_embed_texts_raises_on_missing_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that embed_texts raises ValueError when embedding key is missing."""
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="ollama/nomic-embed-text",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    def fake_embedding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        # Return item without embedding key
        return {"data": [{}]}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    with pytest.raises(ValueError, match="invalid_embedding_format"):
        embed_texts(["hello"], settings=get_settings())


def test_embed_texts_error_includes_item_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that error message includes the item index for batch debugging."""
    _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="ollama/nomic-embed-text",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    def fake_embedding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        # First two valid, third malformed
        return {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
                {"embedding": None},  # Malformed at index 2
            ]
        }

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    with pytest.raises(ValueError, match=r"item 2.*NoneType"):
        embed_texts(["a", "b", "c"], settings=get_settings())
