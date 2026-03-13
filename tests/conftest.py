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
from cloop.settings import (
    EmbedStorageMode,
    PiThinkingLevel,
    Settings,
    ToolMode,
    VectorSearchMode,
    get_settings,
)

STREAM_TOKENS = ["Answer ", "segment"]


@pytest.fixture
def test_settings() -> Callable[..., Settings]:
    """Factory fixture returning a function to create Settings with test defaults.

    Returns a function that creates Settings objects with sensible test defaults.
    Pass keyword arguments to override specific fields.

    Usage:
        # Default settings
        settings = test_settings()

        # Override specific fields
        settings = test_settings(autopilot_enabled=True, llm_timeout=60.0)

    Returns:
        A factory function that creates Settings objects.
    """

    def _factory(**overrides: Any) -> Settings:
        defaults = {
            "root_dir": Path.cwd(),
            "core_db_path": Path("./data/core.db"),
            "rag_db_path": Path("./data/rag.db"),
            "pi_model": "mock-llm",
            "embed_model": "ollama/nomic-embed-text",
            "default_top_k": 5,
            "chunk_size": 800,
            "pi_timeout": 30.0,
            "ingest_timeout": 60.0,
            "embedding_timeout": 30.0,
            "sqlite_vector_extension": None,
            "vector_search_mode": VectorSearchMode.PYTHON,
            "tool_mode_default": ToolMode.MANUAL,
            "embed_storage_mode": EmbedStorageMode.DUAL,
            "pi_bridge_cmd": "node ./src/cloop/pi_bridge/bridge.mjs",
            "pi_agent_dir": None,
            "pi_thinking_level": PiThinkingLevel.NONE,
            "pi_organizer_model": "google/gemini-3-flash-preview",
            "pi_organizer_timeout": 20.0,
            "pi_organizer_thinking_level": PiThinkingLevel.NONE,
            "pi_max_tool_rounds": 1,
            "openai_api_base": None,
            "openai_api_key": None,
            "google_api_key": None,
            "ollama_api_base": None,
            "lmstudio_api_base": None,
            "openrouter_api_base": None,
            "stream_default": False,
            "autopilot_enabled": False,
            "autopilot_autoapply_min_confidence": 0.85,
            "max_file_size_mb": 50,
            "prioritization_due_window_hours": 72.0,
            "due_soon_hours": 48.0,
            "prioritization_quick_win_minutes": 15,
            "prioritization_high_leverage_threshold": 0.7,
            "priority_weight_due": 1.0,
            "priority_weight_urgency": 0.7,
            "priority_weight_importance": 0.9,
            "priority_weight_time_penalty": 0.2,
            "priority_weight_activation_penalty": 0.3,
            "priority_weight_blocked_penalty": 10.0,
            "related_similarity_threshold": 0.78,
            "duplicate_similarity_threshold": 0.95,
            "related_max_candidates": 1000,
            "next_candidates_limit": 500,
            "idempotency_ttl_seconds": 86400,
            "idempotency_max_key_length": 255,
            "webhook_max_retries": 5,
            "webhook_retry_base_delay": 2.0,
            "webhook_retry_max_delay": 300.0,
            "webhook_timeout_seconds": 30.0,
            "webhook_heartbeat_interval": 30.0,
            "llm_max_retries": 3,
            "llm_retry_min_wait": 2.0,
            "llm_retry_max_wait": 60.0,
            "claim_default_ttl_seconds": 300,
            "claim_max_ttl_seconds": 3600,
            "claim_token_bytes": 32,
            "backup_dir": Path("./data/backups"),
            "backup_keep_count": 10,
            "backup_compress": True,
            "review_stale_hours": 72.0,
            "review_blocked_hours": 48.0,
            "operation_metrics_enabled": False,
            "scheduler_enabled": False,
            "scheduler_daily_review_interval_hours": 24.0,
            "scheduler_weekly_review_interval_hours": 168.0,
            "scheduler_due_soon_nudge_interval_hours": 1.0,
            "scheduler_stale_rescue_interval_hours": 6.0,
            "scheduler_poll_interval_seconds": 60.0,
            "scheduler_lease_seconds": 180,
        }
        defaults.update(overrides)
        return Settings(**defaults)  # type: ignore[arg-type]

    return _factory


def _now_iso() -> str:
    """Return current UTC time as ISO8601 string with seconds precision.

    This is a shared test utility for generating consistent datetime strings.
    Used by test_db_failures.py, test_mcp_server.py, test_loops_query.py, test_loop_*.py.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure a temporary data directory for test isolation.

    This fixture is the standard pattern for all tests that need a data directory.
    pytest automatically cleans up tmp_path after the test session completes.
    """
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "false")
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
        monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
        monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
        monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "false")
        get_settings.cache_clear()
        db.init_databases(get_settings())
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    return _factory


@pytest.fixture
def mock_completion_response() -> Dict[str, Any]:
    """Return a simple mock bridge-backed completion payload."""
    return {
        "message": "mock-response",
        "metadata": {"model": "mock-llm", "latency_ms": 0.0, "usage": {}},
    }


@pytest.fixture
def mock_tool_call_response() -> Dict[str, Any]:
    """Return a mock bridge-backed tool run."""
    return {
        "message": "tool-mode-final",
        "metadata": {
            "model": "mock-llm-tool",
            "latency_ms": 0.0,
            "usage": {},
            "tool_outputs": [
                {
                    "name": "write_note",
                    "output": {"action": "write_note", "note": {"id": 1}},
                    "is_error": False,
                }
            ],
        },
        "tool_calls": [{"name": "write_note", "arguments": {"title": "auto", "body": "generated"}}],
    }


@pytest.fixture
def mock_tool_final_response() -> Dict[str, Any]:
    """Return a compatibility-shaped final tool response for legacy contract checks."""
    return {
        "message": "tool-mode-final",
        "metadata": {"model": "mock-llm-tool", "latency_ms": 0.0, "usage": {}},
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
def mock_stream_events() -> Any:
    """Factory fixture returning a mock bridge event stream."""

    def _stream(*args: Any, **kwargs: Any) -> Iterator[Dict[str, Any]]:
        for token in STREAM_TOKENS:
            yield {"type": "text_delta", "delta": token}
        yield {
            "type": "done",
            "model": "mock-llm",
            "latency_ms": 1.0,
            "usage": {},
        }

    return _stream


@pytest.fixture
def mock_completion(
    mock_completion_response: Dict[str, Any],
    mock_tool_call_response: Dict[str, Any],
) -> Any:
    """Factory fixture returning a bridge-backed completion shim."""

    def _completion(messages: List[Dict[str, Any]], *args: Any, **kwargs: Any):
        tools = kwargs.get("tools") or (args[0] if args else None)
        if tools:
            return (
                mock_tool_call_response["message"],
                mock_tool_call_response["metadata"],
                mock_tool_call_response["tool_calls"],
            )
        return mock_completion_response["message"], mock_completion_response["metadata"]

    return _completion


@pytest.fixture
def test_client(
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_completion: Any,
    mock_embedding_response: Any,
    mock_stream_events: Any,
) -> TestClient:
    """Create a TestClient with all LLM/embedding mocks configured.

    This fixture:
    1. Sets up a temporary data directory
    2. Disables autopilot to avoid background enrichment
    3. Patches bridge-backed chat functions and embedding calls
    4. Patches bridge health and streaming helpers in importing modules
    5. Returns a TestClient ready for API testing
    """
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()

    monkeypatch.setattr("cloop.llm.chat_completion", mock_completion)
    monkeypatch.setattr("cloop.routes.chat.chat_completion", mock_completion)
    monkeypatch.setattr("cloop.rag.ask_orchestration.chat_completion", mock_completion)
    monkeypatch.setattr("cloop.llm.chat_with_tools", mock_completion)
    monkeypatch.setattr("cloop.routes.chat.chat_with_tools", mock_completion)
    monkeypatch.setattr("cloop.llm.stream_events", mock_stream_events)
    monkeypatch.setattr("cloop.routes.chat.stream_events", mock_stream_events)
    monkeypatch.setattr("cloop.routes.rag.stream_events", mock_stream_events)
    monkeypatch.setattr(
        "cloop.main.bridge_health",
        lambda settings: {"bridge": "cloop-pi-bridge", "version": "0.1.0", "latency_ms": 1.0},
    )
    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_embedding_response)
    return TestClient(app)
