from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.embeddings import embed_texts
from cloop.llm import chat_completion, chat_with_tools
from cloop.settings import Settings, get_settings


def _configure_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


class _FakeSession:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.tool_results: list[dict[str, Any]] = []
        self.aborted = False

    def events(self):
        yield from self._events

    def send_tool_result(
        self, *, tool_call_id: str, payload: dict[str, Any], is_error: bool
    ) -> None:
        self.tool_results.append(
            {
                "tool_call_id": tool_call_id,
                "payload": payload,
                "is_error": is_error,
            }
        )

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        return None


class _FakeRuntime:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.requests: list[Any] = []

    def open_session(self, request):
        self.requests.append(request)
        return self.session


def test_chat_completion_uses_bridge_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_PI_MODEL="openai/gpt-5.4",
    )
    runtime = _FakeRuntime(
        _FakeSession(
            [
                {"type": "text_delta", "delta": "hi"},
                {
                    "type": "done",
                    "model": "openai/gpt-5.4",
                    "provider": "openai",
                    "api": "openai-responses",
                    "usage": {"totalTokens": 0},
                    "stop_reason": "stop",
                },
            ]
        )
    )

    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    content, metadata = chat_completion(
        [{"role": "user", "content": "Hello"}],
        settings=settings,
    )

    assert content == "hi"
    assert metadata["model"] == "openai/gpt-5.4"
    assert runtime.requests[0].model == "openai/gpt-5.4"
    assert runtime.requests[0].messages == [{"role": "user", "content": "Hello"}]


def test_chat_with_tools_executes_python_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(monkeypatch, tmp_path, CLOOP_PI_MODEL="openai/gpt-5.4")
    session = _FakeSession(
        [
            {
                "type": "tool_call",
                "tool_call_id": "call-1",
                "name": "write_note",
                "arguments": {"title": "auto", "body": "generated"},
            },
            {"type": "text_delta", "delta": "done"},
            {
                "type": "done",
                "model": "openai/gpt-5.4",
                "provider": "openai",
                "api": "openai-responses",
                "usage": {},
                "stop_reason": "stop",
            },
        ]
    )
    runtime = _FakeRuntime(session)
    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    content, metadata, tool_calls = chat_with_tools(
        [{"role": "user", "content": "write a note"}],
        settings=settings,
    )

    assert content == "done"
    assert tool_calls == [
        {"name": "write_note", "arguments": {"title": "auto", "body": "generated"}}
    ]
    assert session.tool_results[0]["payload"]["action"] == "write_note"
    assert metadata["tool_outputs"][0]["name"] == "write_note"


def test_embed_texts_forward_provider_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="ollama/nomic-embed-text",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    captured: dict[str, Any] = {}

    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    vectors = embed_texts(["hello"], settings=settings)
    assert np.allclose(vectors[0], np.array([0.1, 0.2, 0.3], dtype=np.float32))
    assert captured.get("api_base") == "http://localhost:11434/v1"


def test_embed_texts_raises_on_malformed_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="ollama/nomic-embed-text",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"data": [{"embedding": "not-a-list"}]}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    with pytest.raises(ValueError, match="invalid_embedding_format"):
        embed_texts(["hello"], settings=settings)


def test_embed_texts_error_includes_item_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_EMBED_MODEL="ollama/nomic-embed-text",
        CLOOP_OLLAMA_API_BASE="http://localhost:11434/v1",
    )

    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
                {"embedding": None},
            ]
        }

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)

    with pytest.raises(ValueError, match=r"item 2.*NoneType"):
        embed_texts(["a", "b", "c"], settings=settings)
