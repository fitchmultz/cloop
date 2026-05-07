"""Unit coverage for the shared pi-backed LLM facade.

Purpose:
    Verify selector resolution, per-surface tool budgets, alternate strategies,
    tool execution, and bridge failure shaping for `cloop.llm`.

Responsibilities:
    - Assert bridge requests inherit the correct selector metadata
    - Assert per-surface tool-round budgets resolve correctly
    - Assert bounded read-only alternate strategies behave as designed
    - Assert Python-owned tools execute through the bridge loop
    - Assert tool-round exhaustion preserves structured metadata

Non-scope:
    - End-to-end HTTP transport behavior
    - Real upstream pi availability
"""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.ai_bridge.errors import BridgeUpstreamError, ReadOnlyGenerationExhaustedError
from cloop.ai_bridge.protocol import BridgeToolSpec
from cloop.embeddings import embed_texts
from cloop.llm import chat_completion, chat_with_tools, stream_events
from cloop.settings import PiToolBudgetSurface, Settings, get_settings


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
        self.closed = False

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
        self.closed = True


class _FailingSession(_FakeSession):
    def __init__(self, exc: BridgeUpstreamError) -> None:
        super().__init__([])
        self.exc = exc

    def events(self):
        yield {"type": "text_delta", "delta": "draft"}
        raise self.exc


class _ImmediateFailingSession(_FakeSession):
    def __init__(self, exc: BridgeUpstreamError) -> None:
        super().__init__([])
        self.exc = exc

    def events(self):
        raise self.exc


class _QueuedRuntime:
    def __init__(self, sessions: list[_FakeSession], resolutions: list[dict[str, Any]]) -> None:
        self._sessions = list(sessions)
        self._resolutions = list(resolutions)
        self.requests: list[Any] = []
        self.resolve_requests: list[dict[str, Any]] = []

    def resolve_model(
        self, *, selectors: tuple[str, ...], selector_mode: str, timeout_s: float = 5.0
    ):
        current = self._resolutions.pop(0)
        self.resolve_requests.append(
            {
                "selectors": selectors,
                "selector_mode": selector_mode,
                "timeout_s": timeout_s,
            }
        )

        class Resolution:
            def __init__(self, payload: dict[str, Any]) -> None:
                self.requested_selector = payload["requested_selector"]
                self.requested_selectors = tuple(payload["requested_selectors"])
                self.resolved_selector = payload["resolved_selector"]
                self.fallback_used = payload["fallback_used"]
                self.selector_mode = payload["selector_mode"]

        return Resolution(current)

    def open_session(self, request):
        self.requests.append(request)
        return self._sessions.pop(0)


def _resolution(
    *,
    requested_selector: str,
    requested_selectors: tuple[str, ...],
    resolved_selector: str,
    fallback_used: bool = False,
    selector_mode: str = "fallback",
) -> dict[str, Any]:
    return {
        "requested_selector": requested_selector,
        "requested_selectors": requested_selectors,
        "resolved_selector": resolved_selector,
        "fallback_used": fallback_used,
        "selector_mode": selector_mode,
    }


def test_chat_completion_uses_bridge_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_PI_MODEL="zai/glm-5.1,kimi-coding/k2p6",
    )
    runtime = _QueuedRuntime(
        sessions=[
            _FakeSession(
                [
                    {"type": "text_delta", "delta": "hi"},
                    {
                        "type": "done",
                        "model": "kimi-coding/k2p6",
                        "provider": "kimi-coding",
                        "api": "zai-chat",
                        "usage": {"totalTokens": 0},
                        "stop_reason": "stop",
                    },
                ]
            )
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1", "kimi-coding/k2p6"),
                resolved_selector="kimi-coding/k2p6",
                fallback_used=True,
            )
        ],
    )

    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    content, metadata = chat_completion(
        [{"role": "user", "content": "Hello"}],
        surface=PiToolBudgetSurface.CHAT,
        settings=settings,
    )

    assert content == "hi"
    assert metadata["model"] == "kimi-coding/k2p6"
    assert metadata["requested_selector"] == "zai/glm-5.1"
    assert metadata["resolved_selector"] == "kimi-coding/k2p6"
    assert metadata["fallback_used"] is True
    assert metadata["generation_strategy"] == "primary"
    assert metadata["alternate_strategy_used"] is False
    assert metadata["strategy_attempts"] == [
        {
            "attempt": 1,
            "strategy": "primary",
            "reason": None,
            "surface": "chat",
            "requested_selector": "zai/glm-5.1",
            "requested_selectors": ["zai/glm-5.1", "kimi-coding/k2p6"],
            "resolved_selector": "kimi-coding/k2p6",
            "fallback_used": True,
            "selector_mode": "fallback",
            "max_tool_rounds": 4,
            "tool_count": 0,
            "success": True,
        }
    ]
    assert runtime.resolve_requests[0]["selectors"] == ("zai/glm-5.1", "kimi-coding/k2p6")
    assert runtime.requests[0].model == "kimi-coding/k2p6"
    assert runtime.requests[0].messages == [{"role": "user", "content": "Hello"}]


def test_chat_completion_falls_back_to_next_selector_on_retryable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_PI_MODEL="zai/glm-5.1,kimi-coding/k2p6",
    )
    runtime = _QueuedRuntime(
        sessions=[
            _ImmediateFailingSession(
                BridgeUpstreamError("provider_timeout", "timeout", retryable=True)
            ),
            _FakeSession(
                [
                    {"type": "text_delta", "delta": "recovered"},
                    {
                        "type": "done",
                        "model": "kimi-coding/k2p6",
                        "provider": "kimi-coding",
                        "api": "zai-chat",
                        "usage": {},
                        "stop_reason": "stop",
                    },
                ]
            ),
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1", "kimi-coding/k2p6"),
                resolved_selector="zai/glm-5.1",
            ),
            _resolution(
                requested_selector="kimi-coding/k2p6",
                requested_selectors=("kimi-coding/k2p6",),
                resolved_selector="kimi-coding/k2p6",
            ),
        ],
    )

    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    content, metadata = chat_completion(
        [{"role": "user", "content": "Recover"}],
        surface=PiToolBudgetSurface.CHAT,
        settings=settings,
    )

    assert content == "recovered"
    assert metadata["generation_strategy"] == "fallback_selector"
    assert metadata["alternate_strategy_used"] is True
    assert metadata["strategy_reason"] == "retryable upstream failure on the resolved selector"
    assert [attempt["success"] for attempt in metadata["strategy_attempts"]] == [False, True]
    assert metadata["strategy_attempts"][0]["error_code"] == "provider_timeout"
    assert runtime.resolve_requests[1]["selectors"] == ("kimi-coding/k2p6",)
    assert runtime.requests[1].model == "kimi-coding/k2p6"


def test_chat_completion_retries_same_selector_when_no_fallback_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(monkeypatch, tmp_path, CLOOP_PI_MODEL="zai/glm-5.1")
    runtime = _QueuedRuntime(
        sessions=[
            _ImmediateFailingSession(
                BridgeUpstreamError("provider_timeout", "timeout", retryable=True)
            ),
            _FakeSession(
                [
                    {"type": "text_delta", "delta": "retry worked"},
                    {
                        "type": "done",
                        "model": "zai/glm-5.1",
                        "provider": "zai",
                        "api": "zai-chat",
                        "usage": {},
                        "stop_reason": "stop",
                    },
                ]
            ),
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            ),
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
                selector_mode="exact",
            ),
        ],
    )

    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    content, metadata = chat_completion(
        [{"role": "user", "content": "Retry same selector"}],
        surface=PiToolBudgetSurface.CHAT,
        settings=settings,
    )

    assert content == "retry worked"
    assert metadata["generation_strategy"] == "retry_same_selector"
    assert runtime.resolve_requests[1]["selectors"] == ("zai/glm-5.1",)
    assert runtime.resolve_requests[1]["selector_mode"] == "exact"


def test_stream_events_does_not_retry_after_visible_output_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_PI_MODEL="zai/glm-5.1,kimi-coding/k2p6",
    )
    runtime = _QueuedRuntime(
        sessions=[
            _FailingSession(BridgeUpstreamError("provider_timeout", "timeout", retryable=True))
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1", "kimi-coding/k2p6"),
                resolved_selector="zai/glm-5.1",
            )
        ],
    )

    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    iterator = stream_events(
        [{"role": "user", "content": "hello"}],
        surface=PiToolBudgetSurface.CHAT,
        settings=settings,
    )
    first_event = next(iterator)
    assert first_event == {"type": "text_delta", "delta": "draft"}

    with pytest.raises(ReadOnlyGenerationExhaustedError, match="chat") as exc_info:
        next(iterator)

    assert exc_info.value.details["exhaustion_reason"] == "response_started"
    assert len(runtime.requests) == 1


def test_readonly_tool_loop_failure_deescalates_to_no_tool_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(monkeypatch, tmp_path, CLOOP_PI_MODEL="zai/glm-5.1")
    runtime = _QueuedRuntime(
        sessions=[
            _ImmediateFailingSession(
                BridgeUpstreamError(
                    "tool_round_limit",
                    "tool budget exceeded",
                    retryable=True,
                    details={"tool_rounds_used": 2, "max_tool_rounds": 2},
                )
            ),
            _FakeSession(
                [
                    {"type": "text_delta", "delta": "deescalated"},
                    {
                        "type": "done",
                        "model": "zai/glm-5.1",
                        "provider": "zai",
                        "api": "zai-chat",
                        "usage": {},
                        "stop_reason": "stop",
                    },
                ]
            ),
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            ),
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
                selector_mode="exact",
            ),
        ],
    )
    tools = [
        BridgeToolSpec(
            name="read_note",
            description="Read a note",
            input_schema={"type": "object", "properties": {}},
        )
    ]

    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    events = list(
        stream_events(
            [{"role": "user", "content": "Use tools if needed"}],
            surface=PiToolBudgetSurface.CHAT,
            settings=settings,
            tools=tools,
            max_tool_rounds=2,
        )
    )
    done_event = events[-1]

    assert done_event["generation_strategy"] == "no_tool_lower_budget"
    assert done_event["alternate_strategy_used"] is True
    assert runtime.requests[0].tools == tools
    assert runtime.requests[1].tools == []
    assert runtime.requests[1].max_tool_rounds == 1


def test_mutation_surface_never_uses_alternate_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(monkeypatch, tmp_path, CLOOP_PI_MODEL="zai/glm-5.1")
    runtime = _QueuedRuntime(
        sessions=[
            _ImmediateFailingSession(
                BridgeUpstreamError("provider_timeout", "timeout", retryable=True)
            )
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            )
        ],
    )

    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)
    monkeypatch.setattr("cloop.llm.get_agent_bridge_tools", lambda: [])

    with pytest.raises(BridgeUpstreamError, match="timeout"):
        chat_with_tools(
            [{"role": "user", "content": "do work"}],
            surface=PiToolBudgetSurface.MUTATION,
            settings=settings,
        )

    assert len(runtime.requests) == 1


def test_chat_with_tools_executes_python_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(monkeypatch, tmp_path, CLOOP_PI_MODEL="zai/glm-5.1")
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
                "model": "zai/glm-5.1",
                "provider": "zai",
                "api": "zai-chat",
                "usage": {},
                "stop_reason": "stop",
            },
        ]
    )
    runtime = _QueuedRuntime(
        sessions=[session],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            )
        ],
    )
    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    content, metadata, tool_calls = chat_with_tools(
        [{"role": "user", "content": "write a note"}],
        surface=PiToolBudgetSurface.MUTATION,
        settings=settings,
    )

    assert content == "done"
    assert tool_calls == [
        {"name": "write_note", "arguments": {"title": "auto", "body": "generated"}}
    ]
    assert session.tool_results[0]["payload"]["action"] == "write_note"
    assert metadata["tool_outputs"][0]["name"] == "write_note"


def test_stream_events_aborts_unfinished_bridge_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(monkeypatch, tmp_path, CLOOP_PI_MODEL="zai/glm-5.1")
    session = _FakeSession([{"type": "text_delta", "delta": "partial"}])
    runtime = _QueuedRuntime(
        sessions=[session],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            )
        ],
    )
    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    events = list(
        stream_events(
            [{"role": "user", "content": "Hello"}],
            surface=PiToolBudgetSurface.CHAT,
            settings=settings,
        )
    )

    assert events == [{"type": "text_delta", "delta": "partial"}]
    assert session.aborted is True
    assert session.closed is True


@pytest.mark.parametrize(
    ("surface", "env_key", "env_value"),
    [
        (PiToolBudgetSurface.CHAT, "CLOOP_PI_CHAT_MAX_TOOL_ROUNDS", "5"),
        (PiToolBudgetSurface.PLANNING, "CLOOP_PI_PLANNING_MAX_TOOL_ROUNDS", "3"),
        (PiToolBudgetSurface.ENRICHMENT, "CLOOP_PI_ENRICHMENT_MAX_TOOL_ROUNDS", "4"),
        (PiToolBudgetSurface.RAG, "CLOOP_PI_RAG_MAX_TOOL_ROUNDS", "6"),
        (PiToolBudgetSurface.MUTATION, "CLOOP_PI_MUTATION_MAX_TOOL_ROUNDS", "2"),
    ],
)
def test_stream_events_uses_surface_budget_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: PiToolBudgetSurface,
    env_key: str,
    env_value: str,
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_PI_MODEL="zai/glm-5.1",
        **{env_key: env_value},
    )
    runtime = _QueuedRuntime(
        sessions=[
            _FakeSession(
                [
                    {"type": "text_delta", "delta": "done"},
                    {
                        "type": "done",
                        "model": "zai/glm-5.1",
                        "provider": "zai",
                        "api": "zai-chat",
                        "usage": {},
                        "stop_reason": "stop",
                    },
                ]
            )
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            )
        ],
    )
    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    list(
        stream_events(
            [{"role": "user", "content": "hello"}],
            surface=surface,
            settings=settings,
        )
    )

    assert runtime.requests[0].max_tool_rounds == int(env_value)


def test_stream_events_explicit_override_wins_over_surface_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_PI_MODEL="zai/glm-5.1",
        CLOOP_PI_RAG_MAX_TOOL_ROUNDS="6",
    )
    runtime = _QueuedRuntime(
        sessions=[
            _FakeSession(
                [
                    {"type": "text_delta", "delta": "done"},
                    {
                        "type": "done",
                        "model": "zai/glm-5.1",
                        "provider": "zai",
                        "api": "zai-chat",
                        "usage": {},
                        "stop_reason": "stop",
                    },
                ]
            )
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            )
        ],
    )
    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    list(
        stream_events(
            [{"role": "user", "content": "hello"}],
            surface=PiToolBudgetSurface.RAG,
            settings=settings,
            max_tool_rounds=7,
        )
    )

    assert runtime.requests[0].max_tool_rounds == 7


def test_tool_round_limit_error_includes_structured_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _configure_env(
        monkeypatch,
        tmp_path,
        CLOOP_PI_MODEL="zai/glm-5.1",
        CLOOP_PI_CHAT_MAX_TOOL_ROUNDS="2",
    )
    runtime = _QueuedRuntime(
        sessions=[
            _FailingSession(
                BridgeUpstreamError(
                    "tool_round_limit",
                    "tool budget exceeded",
                    details={"tool_rounds_used": 3, "max_tool_rounds": 2},
                )
            )
        ],
        resolutions=[
            _resolution(
                requested_selector="zai/glm-5.1",
                requested_selectors=("zai/glm-5.1",),
                resolved_selector="zai/glm-5.1",
            )
        ],
    )
    monkeypatch.setattr("cloop.llm.get_bridge_runtime", lambda _settings: runtime)

    with pytest.raises(BridgeUpstreamError, match="tool budget exceeded") as exc_info:
        list(
            stream_events(
                [{"role": "user", "content": "hello"}],
                surface=PiToolBudgetSurface.CHAT,
                settings=settings,
            )
        )

    assert exc_info.value.code == "tool_round_limit"
    assert exc_info.value.details["surface"] == "chat"
    assert exc_info.value.details["tool_rounds_used"] == 3
    assert exc_info.value.details["max_tool_rounds"] == 2
    assert exc_info.value.details["partial_results"]["text"] == "draft"
    assert exc_info.value.details["partial_results"]["tool_calls"] == []
    assert "suggested_actions" in exc_info.value.details["guidance"]


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
