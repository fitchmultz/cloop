"""Shared pytest fixtures and test utilities for Cloop tests.

This module provides:
- Centralized mock factories for LLM and embedding responses
- Datetime helpers (_now_iso) for consistent timestamp generation
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.main import app
from cloop.settings import get_settings

STREAM_TOKENS = ["Answer ", "segment"]


def _now_iso() -> str:
    """Return current UTC time as ISO8601 string with seconds precision.

    This is a shared test utility for generating consistent datetime strings.
    Used by test_loops.py, test_db_failures.py, test_mcp_server.py, test_loops_query.py.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
def make_test_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., TestClient]:
    """Factory fixture returning a function to create isolated test clients.

    This provides a bare TestClient without the full mock setup from the
    test_client fixture. Use this when tests need to inject their own
    mocks (e.g., for error testing).

    Args:
        data_dir: Optional path for data directory. Defaults to tmp_path.
        raise_server_exceptions: If False, server exceptions return 500
            responses instead of raising in the test. Default True.

    Returns:
        A function that creates a TestClient with isolated database.

    Usage:
        # Standard usage (uses tmp_path)
        client = make_test_client()

        # For error testing
        client = make_test_client(raise_server_exceptions=False)

        # Custom data directory (e.g., for import isolation)
        client = make_test_client(data_dir=tmp_path / "subdir")
    """

    def _factory(data_dir: Path | None = None, raise_server_exceptions: bool = True) -> TestClient:
        target_dir = data_dir or tmp_path
        monkeypatch.setenv("CLOOP_DATA_DIR", str(target_dir))
        monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
        monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
        monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
        get_settings.cache_clear()
        db.init_databases(get_settings())
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    return _factory


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
    2. Disables autopilot to avoid background enrichment
    3. Patches litellm.completion and litellm.embedding
    4. Patches stream_completion in all modules that import it
    5. Returns a TestClient ready for API testing
    """
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()

    monkeypatch.setattr("cloop.llm.litellm.completion", mock_completion)
    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_embedding_response)
    monkeypatch.setattr("cloop.llm.stream_completion", mock_stream_completion)
    monkeypatch.setattr("cloop.routes.chat.stream_completion", mock_stream_completion)
    monkeypatch.setattr("cloop.routes.rag.stream_completion", mock_stream_completion)
    return TestClient(app)
