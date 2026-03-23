"""Shared pytest fixtures and test utilities for Cloop tests.

Purpose:
    Provide reusable pytest fixtures and test helpers for isolated Cloop test runs.

Responsibilities:
    - Build isolated settings and FastAPI clients for tests.
    - Provide common mock factories for LLM and embedding responses.
    - Provide shared timestamp and durable-record seed helpers.

Non-scope:
    - Feature-specific assertions or test-only business logic.

Usage:
    Imported automatically by pytest and directly by tests that need shared helpers.

Invariants/Assumptions:
    - Helpers target the public Cloop DB/bootstrap surfaces.
    - Temporary data directories stay isolated per test.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.ai_bridge import shutdown_bridge_runtime
from cloop.settings import (
    EmbedStorageMode,
    PiSelectorMode,
    PiThinkingLevel,
    Settings,
    ToolMode,
    VectorSearchMode,
    get_settings,
)

STREAM_TOKENS = ["Answer ", "segment"]


def _get_app() -> Any:
    """Import and return the canonical FastAPI app only when a fixture needs it."""
    from cloop.main import app

    return app


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
            "pi_model_preferences": ("mock-llm",),
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
            "pi_organizer_model_preferences": ("mock-organizer",),
            "pi_selector_mode": PiSelectorMode.FALLBACK,
            "pi_organizer_timeout": 20.0,
            "pi_organizer_thinking_level": PiThinkingLevel.NONE,
            "pi_chat_max_tool_rounds": 4,
            "pi_planning_max_tool_rounds": 2,
            "pi_enrichment_max_tool_rounds": 2,
            "pi_rag_max_tool_rounds": 2,
            "pi_mutation_max_tool_rounds": 2,
            "pi_readonly_alternate_strategy_enabled": True,
            "pi_readonly_lower_budget_max_tool_rounds": 1,
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


def insert_planning_session(session_id: int, *, name: str | None = None) -> None:
    """Insert a minimal planning session row for continuity/planning tests."""
    with db.core_connection(get_settings()) as conn:
        conn.execute(
            """
            INSERT INTO planning_sessions (
                id,
                name,
                prompt,
                query,
                options_json,
                plan_json,
                current_checkpoint_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                name or f"Planning session {session_id}",
                "Test planning prompt",
                None,
                "{}",
                '{"workflow": {"checkpoints": []}}',
                0,
            ),
        )
        conn.commit()


def insert_scheduler_push_delivery(
    *,
    notification_id: str,
    workflow_thread_id: str,
    slot_key: str = "2026-03-21T12:00:00Z",
    delivery_status: str = "sent",
    delivery_reason: str | None = None,
    push_count: int = 1,
    claimed_at: str = "2026-03-21T12:00:10Z",
    send_started_at: str | None = "2026-03-21T12:00:11Z",
    send_completed_at: str | None = "2026-03-21T12:00:12Z",
) -> None:
    """Insert one scheduler push-delivery row for continuity diagnostics tests."""
    payload = {"event_type": "review_generated"}
    if delivery_reason is not None:
        payload["delivery_reason"] = delivery_reason
    with db.core_connection(get_settings()) as conn:
        conn.execute(
            """
            INSERT INTO scheduler_push_deliveries (
                task_name,
                slot_key,
                push_kind,
                payload_json,
                notification_id,
                workflow_thread_id,
                claimed_at,
                send_started_at,
                send_completed_at,
                delivery_status,
                push_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "daily_review",
                slot_key,
                "review_generated",
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                notification_id,
                workflow_thread_id,
                claimed_at,
                send_started_at,
                send_completed_at,
                delivery_status,
                push_count,
            ),
        )
        conn.commit()


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure a temporary data directory for test isolation.

    This fixture is the standard pattern for all tests that need a data directory.
    pytest automatically cleans up tmp_path after the test session completes.
    """
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_PI_ORGANIZER_MODEL", "mock-organizer")
    monkeypatch.setenv("CLOOP_PI_SELECTOR_MODE", "fallback")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return tmp_path


@pytest.fixture(autouse=True)
def cleanup_bridge_runtime() -> Iterator[None]:
    """Stop any leaked singleton pi bridge after each test."""
    try:
        yield
    finally:
        shutdown_bridge_runtime()


@pytest.fixture
def make_test_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., TestClient]]:
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
    """

    clients: list[TestClient] = []

    def _factory(data_dir: Path | None = None, raise_server_exceptions: bool = True) -> TestClient:
        target_dir = data_dir or tmp_path
        monkeypatch.setenv("CLOOP_DATA_DIR", str(target_dir))
        monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
        monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
        monkeypatch.setenv("CLOOP_PI_ORGANIZER_MODEL", "mock-organizer")
        monkeypatch.setenv("CLOOP_PI_SELECTOR_MODE", "fallback")
        monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
        monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "false")
        get_settings.cache_clear()
        db.init_databases(get_settings())
        client = TestClient(_get_app(), raise_server_exceptions=raise_server_exceptions)
        clients.append(client)
        return client

    try:
        yield _factory
    finally:
        for client in reversed(clients):
            client.close()


@pytest.fixture
def mock_completion_response() -> Dict[str, Any]:
    """Return a simple mock bridge-backed completion payload."""
    return {
        "message": "mock-response",
        "metadata": {
            "model": "mock-llm",
            "requested_selector": "mock-llm",
            "requested_selectors": ["mock-llm"],
            "resolved_selector": "mock-llm",
            "fallback_used": False,
            "selector_mode": "fallback",
            "latency_ms": 0.0,
            "usage": {},
        },
    }


@pytest.fixture
def mock_tool_call_response() -> Dict[str, Any]:
    """Return a mock bridge-backed tool run."""
    return {
        "message": "tool-mode-final",
        "metadata": {
            "model": "mock-llm-tool",
            "requested_selector": "mock-llm",
            "requested_selectors": ["mock-llm"],
            "resolved_selector": "mock-llm-tool",
            "fallback_used": False,
            "selector_mode": "fallback",
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
        "metadata": {
            "model": "mock-llm-tool",
            "requested_selector": "mock-llm",
            "requested_selectors": ["mock-llm"],
            "resolved_selector": "mock-llm-tool",
            "fallback_used": False,
            "selector_mode": "fallback",
            "latency_ms": 0.0,
            "usage": {},
        },
    }


@pytest.fixture
def mock_embedding_response() -> Any:
    """Factory fixture returning a mock embedding function."""

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
            "requested_selector": "mock-llm",
            "requested_selectors": ["mock-llm"],
            "resolved_selector": "mock-llm",
            "fallback_used": False,
            "selector_mode": "fallback",
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
) -> Iterator[TestClient]:
    """Create a TestClient with all LLM/embedding mocks configured."""
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_SCHEDULER_ENABLED", "false")
    get_settings.cache_clear()

    monkeypatch.setattr("cloop.llm.chat_completion", mock_completion)
    monkeypatch.setattr("cloop.chat_execution.chat_completion", mock_completion)
    monkeypatch.setattr("cloop.rag.ask_orchestration.chat_completion", mock_completion)
    monkeypatch.setattr("cloop.llm.chat_with_tools", mock_completion)
    monkeypatch.setattr("cloop.chat_execution.chat_with_tools", mock_completion)
    monkeypatch.setattr("cloop.llm.stream_events", mock_stream_events)
    monkeypatch.setattr("cloop.chat_execution.stream_events", mock_stream_events)
    monkeypatch.setattr("cloop.rag_execution.stream_events", mock_stream_events)
    monkeypatch.setattr(
        "cloop.main.bridge_health",
        lambda settings: {
            "bridge": "cloop-pi-bridge",
            "version": "0.1.0",
            "protocol": 1,
            "latency_ms": 1.0,
            "chat_selector": {
                "requested_selector": "mock-llm",
                "requested_selectors": ["mock-llm"],
                "resolved_selector": "mock-llm",
                "fallback_used": False,
                "selector_mode": "fallback",
                "error": None,
            },
            "organizer_selector": {
                "requested_selector": "mock-organizer",
                "requested_selectors": ["mock-organizer"],
                "resolved_selector": "mock-organizer",
                "fallback_used": False,
                "selector_mode": "fallback",
                "error": None,
            },
        },
    )
    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_embedding_response)
    with TestClient(_get_app()) as client:
        yield client
