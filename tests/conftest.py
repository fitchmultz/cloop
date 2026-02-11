"""Shared pytest fixtures for Cloop tests.

This module provides centralized mock factories for LLM and embedding
responses, ensuring consistent test behavior and documented mock logic.
"""

from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.main import app
from cloop.settings import get_settings

STREAM_TOKENS = ["Answer ", "segment"]


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure a temporary data directory for test isolation."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return tmp_path


@pytest.fixture
def mock_completion_response() -> Dict[str, Any]:
    """Return a simple mock LLM completion response.

    This is the default response when no tools are involved.
    Matches litellm.completion() response format:
    - choices[0].message.content: the text response
    - model: model identifier
    - usage: token usage dict
    """
    return {
        "choices": [{"message": {"content": "mock-response"}}],
        "model": "mock-llm",
        "usage": {"total_tokens": 0},
    }


@pytest.fixture
def mock_tool_call_response() -> Dict[str, Any]:
    """Return a mock LLM response with a tool call.

    Simulates the first pass of tool-enabled chat where the LLM
    decides to call a tool. The mock always calls 'write_note'.

    Matches litellm.completion() tool call format:
    - choices[0].message.tool_calls: list of tool call objects
    - Each tool call has: id, type, function.name, function.arguments
    """
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "write_note",
                                "arguments": '{"title": "auto", "body": "generated"}',
                            },
                        }
                    ]
                }
            }
        ],
        "model": "mock-llm-tool",
        "usage": {"total_tokens": 0},
    }


@pytest.fixture
def mock_tool_final_response() -> Dict[str, Any]:
    """Return a mock LLM response after tool execution.

    Simulates the second pass of tool-enabled chat where the LLM
    has received tool results and produces a final response.

    This response is triggered when messages contain a 'role': 'tool' entry.
    """
    return {
        "choices": [{"message": {"content": "tool-mode-final"}}],
        "model": "mock-llm-tool",
        "usage": {"total_tokens": 0},
    }


@pytest.fixture
def mock_embedding_response() -> Any:
    """Factory fixture returning a mock embedding function.

    Returns a function that mimics litellm.embedding() behavior:
    - Accepts 'input' kwarg (list of strings)
    - Returns dict with 'data' key containing embedding vectors
    - Each vector has unique values based on input index
    """

    def _embedding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        inputs = kwargs.get("input") or []
        vectors = []
        for index, _ in enumerate(inputs):
            vectors.append({"embedding": [0.1 + index, 0.2 + index, 0.3 + index]})
        return {"data": vectors}

    return _embedding


@pytest.fixture
def mock_stream_completion() -> Any:
    """Factory fixture returning a mock streaming completion function.

    Returns a function that yields predefined tokens (STREAM_TOKENS).
    Mimics litellm streaming completion behavior for testing SSE endpoints.
    """

    def _stream(*args: Any, **kwargs: Any) -> Iterator[str]:
        for token in STREAM_TOKENS:
            yield token

    return _stream


@pytest.fixture
def mock_completion(
    mock_completion_response: Dict[str, Any],
    mock_tool_call_response: Dict[str, Any],
    mock_tool_final_response: Dict[str, Any],
) -> Any:
    """Factory fixture returning a mock completion function with conditional logic.

    This fixture centralizes the conditional mock behavior previously embedded
    in make_client. It simulates litellm.completion() with three return paths:

    1. **Tool final response**: When messages contain 'role': 'tool', returns
       mock_tool_final_response. This simulates the LLM's response after
       executing tool calls and receiving results.

    2. **Tool call response**: When 'tools' kwarg is provided but no tool
       messages exist, returns mock_tool_call_response. This simulates the
       LLM deciding to call a tool.

    3. **Simple response**: When no tools are involved, returns
       mock_completion_response. This is the standard chat response.

    This mimics the real chat_with_tools() flow in src/cloop/llm.py which
    makes two completion calls when tools are used.
    """

    def _completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = kwargs.get("messages") or []
        tools = kwargs.get("tools")

        if tools:
            if any(message.get("role") == "tool" for message in messages):
                return mock_tool_final_response
            return mock_tool_call_response

        return mock_completion_response

    return _completion


@pytest.fixture
def test_client(
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_completion: Any,
    mock_embedding_response: Any,
    mock_stream_completion: Any,
) -> TestClient:
    """Create a TestClient with all LLM/embedding mocks configured.

    This fixture:
    1. Sets up a temporary data directory
    2. Patches litellm.completion and litellm.embedding
    3. Patches stream_completion in all modules that import it
    4. Returns a TestClient ready for API testing
    """
    monkeypatch.setattr("cloop.llm.litellm.completion", mock_completion)
    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_embedding_response)
    monkeypatch.setattr("cloop.llm.stream_completion", mock_stream_completion)
    monkeypatch.setattr("cloop.routes.chat.stream_completion", mock_stream_completion)
    monkeypatch.setattr("cloop.routes.rag.stream_completion", mock_stream_completion)
    return TestClient(app)
