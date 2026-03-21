"""Pi-backed chat completion and tool execution.

Purpose:
    Provide the app-facing generative AI facade over the local pi bridge.

Responsibilities:
    - Start bridge-backed chat completions
    - Stream structured events and text deltas
    - Execute Python-owned tools during bridge tool loops
    - Return stable metadata for routes, RAG, planning, and enrichment
    - Apply bounded alternate strategies for read-only generation paths

Non-scope:
    - Embedding generation (see embeddings.py)
    - SSE formatting/HTTP behavior (see routes/)
    - Node bridge subprocess lifecycle (see ai_bridge/runtime.py)
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from .ai_bridge import get_bridge_runtime
from .ai_bridge.errors import BridgeUpstreamError, ReadOnlyGenerationExhaustedError
from .ai_bridge.protocol import BridgeStartRequest, BridgeToolSpec
from .loops.errors import CloopError
from .settings import PiThinkingLevel, PiToolBudgetSurface, Settings, get_settings
from .tools import get_agent_bridge_tools, get_tool_definition, normalize_tool_arguments

Message = dict[str, Any]
LLMEvent = dict[str, Any]

logger = logging.getLogger(__name__)

_UNSET = object()
_READONLY_SURFACES = frozenset(
    {
        PiToolBudgetSurface.CHAT,
        PiToolBudgetSurface.PLANNING,
        PiToolBudgetSurface.ENRICHMENT,
        PiToolBudgetSurface.RAG,
    }
)


class ToolCallError(ValueError):
    """Raised when bridge-specified tool calls are invalid or unsupported."""


class ReadOnlyRetryStrategy(StrEnum):
    """Bounded alternate strategies for read-only generation requests."""

    PRIMARY = "primary"
    RETRY_SAME_SELECTOR = "retry_same_selector"
    FALLBACK_SELECTOR = "fallback_selector"
    NO_TOOL_LOWER_BUDGET = "no_tool_lower_budget"


@dataclass(frozen=True, slots=True)
class _AttemptPlan:
    """Execution overrides for one generation attempt."""

    strategy: ReadOnlyRetryStrategy
    reason: str | None = None
    selectors: tuple[str, ...] | None = None
    selector_mode: str | None = None
    tools: object | list[BridgeToolSpec] | None = _UNSET
    max_tool_rounds: int | None = None


def estimate_tokens(messages: list[Message]) -> int:
    return sum(len((message.get("content") or "").split()) for message in messages)


def _tool_error_payload(exc: Exception) -> dict[str, Any]:
    error_type = "tool_error"
    if isinstance(exc, CloopError):
        error_type = exc.__class__.__name__
    elif isinstance(exc, ValueError):
        error_type = "validation_error"
    return {
        "ok": False,
        "error": {
            "type": error_type,
            "message": str(exc),
        },
    }


def _metadata_from_done(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "latency_ms": float(event.get("latency_ms", 0.0)),
        "model": event.get("resolved_selector") or event.get("model"),
        "provider": event.get("provider"),
        "api": event.get("api"),
        "usage": event.get("usage") or {},
        "stop_reason": event.get("stop_reason"),
        "requested_selector": event.get("requested_selector"),
        "requested_selectors": list(event.get("requested_selectors") or []),
        "resolved_selector": event.get("resolved_selector") or event.get("model"),
        "fallback_used": bool(event.get("fallback_used", False)),
        "selector_mode": event.get("selector_mode"),
        "generation_strategy": event.get(
            "generation_strategy", ReadOnlyRetryStrategy.PRIMARY.value
        ),
        "alternate_strategy_used": bool(event.get("alternate_strategy_used", False)),
        "strategy_reason": event.get("strategy_reason"),
        "strategy_attempts": list(event.get("strategy_attempts") or []),
    }


def _build_request(
    *,
    messages: list[Message],
    model: str,
    thinking_level: PiThinkingLevel,
    timeout_s: float,
    tools: list[BridgeToolSpec] | None,
    max_tool_rounds: int,
) -> BridgeStartRequest:
    return BridgeStartRequest(
        request_id=uuid.uuid4().hex,
        model=model,
        messages=messages,
        thinking_level=thinking_level.value,
        timeout_ms=max(1, int(timeout_s * 1000)),
        max_tool_rounds=max_tool_rounds,
        tools=tools or [],
    )


def _selector_request(
    *,
    settings: Settings,
    selector_role: str,
    model: str | None,
    model_preferences: Sequence[str] | None,
) -> tuple[tuple[str, ...], str]:
    if model is not None:
        return (model,), "exact"
    if model_preferences is not None:
        return tuple(model_preferences), settings.pi_selector_mode.value
    if selector_role == "organizer":
        return settings.pi_organizer_model_preferences, settings.pi_selector_mode.value
    return settings.pi_model_preferences, settings.pi_selector_mode.value


def _resolve_max_tool_rounds(
    *,
    settings: Settings,
    surface: PiToolBudgetSurface,
    max_tool_rounds: int | None,
) -> int:
    if max_tool_rounds is not None:
        return max_tool_rounds
    return settings.pi_tool_round_budget(surface)


def _tool_round_limit_guidance(
    *,
    surface: PiToolBudgetSurface,
    max_tool_rounds: int,
) -> dict[str, Any]:
    suggested_actions = [
        "Retry with a narrower request or smaller grounding scope.",
        "Inspect any partial text and tool traces before rerunning.",
    ]
    if surface is PiToolBudgetSurface.MUTATION:
        suggested_actions.append(
            "Review completed tool outputs before retrying; "
            "Cloop did not continue mutating after the budget was exhausted."
        )
    elif surface is PiToolBudgetSurface.CHAT:
        suggested_actions.append("Disable tool mode if you only need a text response.")
    else:
        suggested_actions.append(
            "Reduce the number of target loops, retrieved chunks, or other grounding inputs."
        )
    return {
        "summary": f"{surface.value} exhausted its tool-round budget ({max_tool_rounds}).",
        "suggested_actions": suggested_actions,
    }


def _is_readonly_surface(surface: PiToolBudgetSurface) -> bool:
    return surface in _READONLY_SURFACES


def _resolve_runtime_options(
    *,
    settings: Settings,
    selector_role: str,
    thinking_level: PiThinkingLevel | None,
    timeout_s: float | None,
) -> tuple[PiThinkingLevel, float]:
    active_thinking = thinking_level or (
        settings.pi_organizer_thinking_level
        if selector_role == "organizer"
        else settings.pi_thinking_level
    )
    active_timeout = (
        timeout_s
        if timeout_s is not None
        else settings.pi_organizer_timeout
        if selector_role == "organizer"
        else settings.pi_timeout
    )
    return active_thinking, active_timeout


def _selectors_for_attempt(
    *,
    settings: Settings,
    selector_role: str,
    model: str | None,
    model_preferences: Sequence[str] | None,
    attempt_plan: _AttemptPlan,
) -> tuple[tuple[str, ...], str]:
    if attempt_plan.selectors is not None:
        return attempt_plan.selectors, attempt_plan.selector_mode or "exact"
    return _selector_request(
        settings=settings,
        selector_role=selector_role,
        model=model,
        model_preferences=model_preferences,
    )


def _remaining_selectors_after(
    *,
    resolved_selector: str,
    requested_selectors: Sequence[str],
) -> tuple[str, ...]:
    selectors = tuple(str(selector) for selector in requested_selectors)
    try:
        current_index = selectors.index(resolved_selector)
    except ValueError:
        return selectors[1:] if len(selectors) > 1 else ()
    return selectors[current_index + 1 :]


def _attempt_snapshot(
    *,
    attempt_state: dict[str, Any],
    success: bool,
    error: BridgeUpstreamError | None = None,
) -> dict[str, Any]:
    payload = {
        "attempt": int(attempt_state.get("attempt", 0)),
        "strategy": attempt_state.get("strategy"),
        "reason": attempt_state.get("reason"),
        "surface": attempt_state.get("surface"),
        "requested_selector": attempt_state.get("requested_selector"),
        "requested_selectors": list(attempt_state.get("requested_selectors") or []),
        "resolved_selector": attempt_state.get("resolved_selector"),
        "fallback_used": bool(attempt_state.get("fallback_used", False)),
        "selector_mode": attempt_state.get("selector_mode"),
        "max_tool_rounds": attempt_state.get("max_tool_rounds"),
        "tool_count": attempt_state.get("tool_count", 0),
        "success": success,
    }
    if error is not None:
        payload["error_code"] = error.code
        payload["error_message"] = str(error)
        payload["retryable"] = error.retryable
        payload["error_details"] = dict(error.details)
    return payload


def _finalize_done_event(
    *,
    event: dict[str, Any],
    resolution: Any,
    start: float,
    attempt_plan: _AttemptPlan,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = dict(event)
    completed["latency_ms"] = (time.monotonic() - start) * 1000
    completed["requested_selector"] = resolution.requested_selector
    completed["requested_selectors"] = list(resolution.requested_selectors)
    completed["resolved_selector"] = resolution.resolved_selector
    completed["fallback_used"] = resolution.fallback_used
    completed["selector_mode"] = resolution.selector_mode
    completed["generation_strategy"] = attempt_plan.strategy.value
    completed["alternate_strategy_used"] = (
        attempt_plan.strategy is not ReadOnlyRetryStrategy.PRIMARY
    )
    completed["strategy_reason"] = attempt_plan.reason
    completed["strategy_attempts"] = [dict(attempt) for attempt in attempts]
    return completed


def _enrich_bridge_error(
    *,
    exc: BridgeUpstreamError,
    surface: PiToolBudgetSurface,
    max_tool_rounds: int,
    partial_text_parts: list[str],
    partial_tool_calls: list[dict[str, Any]],
    partial_tool_results: list[dict[str, Any]],
) -> BridgeUpstreamError:
    if exc.code != "tool_round_limit":
        return exc
    details = dict(exc.details)
    details.update(
        {
            "surface": surface.value,
            "tool_rounds_used": details.get("tool_rounds_used", len(partial_tool_calls)),
            "max_tool_rounds": max_tool_rounds,
            "partial_results": {
                "text": "".join(partial_text_parts),
                "tool_calls": partial_tool_calls,
                "tool_results": partial_tool_results,
            },
            "guidance": _tool_round_limit_guidance(
                surface=surface,
                max_tool_rounds=max_tool_rounds,
            ),
        }
    )
    return BridgeUpstreamError(
        exc.code,
        str(exc),
        retryable=exc.retryable,
        details=details,
    )


def _stream_events_once(
    messages: list[Message],
    *,
    surface: PiToolBudgetSurface,
    settings: Settings,
    model: str | None,
    model_preferences: Sequence[str] | None,
    selector_role: str,
    thinking_level: PiThinkingLevel | None,
    timeout_s: float | None,
    tools: list[BridgeToolSpec] | None,
    max_tool_rounds: int | None,
    attempt_plan: _AttemptPlan,
    attempt_index: int,
    attempt_state: dict[str, Any],
) -> Iterator[LLMEvent]:
    """Yield structured events for one concrete bridge attempt."""
    active_thinking, active_timeout = _resolve_runtime_options(
        settings=settings,
        selector_role=selector_role,
        thinking_level=thinking_level,
        timeout_s=timeout_s,
    )
    active_max_tool_rounds = (
        attempt_plan.max_tool_rounds
        if attempt_plan.max_tool_rounds is not None
        else _resolve_max_tool_rounds(
            settings=settings,
            surface=surface,
            max_tool_rounds=max_tool_rounds,
        )
    )
    active_tools = (
        cast(list[BridgeToolSpec] | None, attempt_plan.tools)
        if attempt_plan.tools is not _UNSET
        else tools
    )
    selectors, selector_mode = _selectors_for_attempt(
        settings=settings,
        selector_role=selector_role,
        model=model,
        model_preferences=model_preferences,
        attempt_plan=attempt_plan,
    )

    runtime = get_bridge_runtime(settings)
    attempt_state.update(
        {
            "attempt": attempt_index,
            "strategy": attempt_plan.strategy.value,
            "reason": attempt_plan.reason,
            "surface": surface.value,
            "requested_selectors": list(selectors),
            "selector_mode": selector_mode,
            "max_tool_rounds": active_max_tool_rounds,
            "tool_count": len(active_tools or []),
        }
    )

    resolution = runtime.resolve_model(
        selectors=selectors,
        selector_mode=selector_mode,
        timeout_s=min(active_timeout, 5.0),
    )
    attempt_state.update(
        {
            "requested_selector": resolution.requested_selector,
            "requested_selectors": list(resolution.requested_selectors),
            "resolved_selector": resolution.resolved_selector,
            "fallback_used": resolution.fallback_used,
            "selector_mode": resolution.selector_mode,
        }
    )
    logger.info(
        "Resolved pi selector",
        extra={
            "selector_role": selector_role,
            "requested_selector": resolution.requested_selector,
            "requested_selectors": list(resolution.requested_selectors),
            "resolved_selector": resolution.resolved_selector,
            "fallback_used": resolution.fallback_used,
            "selector_mode": resolution.selector_mode,
            "surface": surface.value,
            "max_tool_rounds": active_max_tool_rounds,
            "generation_strategy": attempt_plan.strategy.value,
        },
    )

    request = _build_request(
        messages=messages,
        model=resolution.resolved_selector,
        thinking_level=active_thinking,
        timeout_s=active_timeout,
        tools=active_tools,
        max_tool_rounds=active_max_tool_rounds,
    )
    session = runtime.open_session(request)
    start = time.monotonic()
    finished = False
    partial_text_parts: list[str] = []
    partial_tool_calls: list[dict[str, Any]] = []
    partial_tool_results: list[dict[str, Any]] = []

    try:
        try:
            for event in session.events():
                event_type = str(event.get("type"))
                if event_type == "text_delta":
                    delta = str(event.get("delta", ""))
                    if delta:
                        partial_text_parts.append(delta)
                    yield dict(event)
                    continue

                if event_type == "tool_call":
                    tool_name = str(event.get("name", ""))
                    tool_definition = get_tool_definition(tool_name)
                    if tool_definition is None or not tool_definition.agent_exposed:
                        raise ToolCallError(f"Unsupported tool: {tool_name}")
                    arguments = normalize_tool_arguments(event.get("arguments") or {})
                    try:
                        payload = tool_definition.executor(**arguments)
                        is_error = False
                    except (CloopError, ValueError) as tool_exc:
                        payload = _tool_error_payload(tool_exc)
                        is_error = True
                    tool_call_event = {
                        "type": "tool_call",
                        "tool_call_id": event.get("tool_call_id"),
                        "name": tool_name,
                        "arguments": arguments,
                    }
                    tool_result_event = {
                        "type": "tool_result",
                        "tool_call_id": event.get("tool_call_id"),
                        "name": tool_name,
                        "arguments": arguments,
                        "output": payload,
                        "is_error": is_error,
                    }
                    partial_tool_calls.append(dict(tool_call_event))
                    partial_tool_results.append(dict(tool_result_event))
                    session.send_tool_result(
                        tool_call_id=str(event.get("tool_call_id", "")),
                        payload=payload,
                        is_error=is_error,
                    )
                    yield tool_call_event
                    yield tool_result_event
                    continue

                if event_type == "tool_result":
                    continue

                if event_type == "done":
                    finished = True
                    yield _finalize_done_event(
                        event=event,
                        resolution=resolution,
                        start=start,
                        attempt_plan=attempt_plan,
                        attempts=[],
                    )
                    break

                yield dict(event)
        except BridgeUpstreamError as exc:
            raise _enrich_bridge_error(
                exc=exc,
                surface=surface,
                max_tool_rounds=active_max_tool_rounds,
                partial_text_parts=partial_text_parts,
                partial_tool_calls=partial_tool_calls,
                partial_tool_results=partial_tool_results,
            ) from exc
    finally:
        if not finished:
            session.abort()
        session.close()


def _choose_readonly_alternate(
    *,
    surface: PiToolBudgetSurface,
    settings: Settings,
    current_plan: _AttemptPlan,
    attempt_state: dict[str, Any],
    explicit_model: str | None,
    error: BridgeUpstreamError,
    visible_output_started: bool,
) -> tuple[_AttemptPlan | None, str]:
    if not _is_readonly_surface(surface):
        return None, "non_readonly_surface"
    if not settings.pi_readonly_alternate_strategy_enabled:
        return None, "alternate_strategy_disabled"
    if current_plan.strategy is not ReadOnlyRetryStrategy.PRIMARY:
        return None, "alternate_strategy_already_used"
    if not error.retryable:
        return None, "non_retryable_error"
    if visible_output_started:
        return None, "response_started"

    resolved_selector = str(attempt_state.get("resolved_selector") or "")
    active_max_tool_rounds = int(attempt_state.get("max_tool_rounds") or 0)
    tool_count = int(attempt_state.get("tool_count") or 0)

    if tool_count > 0 and error.code == "tool_round_limit" and resolved_selector:
        return (
            _AttemptPlan(
                strategy=ReadOnlyRetryStrategy.NO_TOOL_LOWER_BUDGET,
                reason="retryable tool-loop failure before any visible output",
                selectors=(resolved_selector,),
                selector_mode="exact",
                tools=[],
                max_tool_rounds=min(
                    active_max_tool_rounds,
                    settings.pi_readonly_lower_budget_max_tool_rounds,
                ),
            ),
            "tool_loop_deescalation",
        )

    remaining_selectors = _remaining_selectors_after(
        resolved_selector=resolved_selector,
        requested_selectors=tuple(attempt_state.get("requested_selectors") or ()),
    )
    if explicit_model is None and remaining_selectors:
        return (
            _AttemptPlan(
                strategy=ReadOnlyRetryStrategy.FALLBACK_SELECTOR,
                reason="retryable upstream failure on the resolved selector",
                selectors=remaining_selectors,
                selector_mode="fallback",
            ),
            "fallback_selector",
        )

    if resolved_selector:
        return (
            _AttemptPlan(
                strategy=ReadOnlyRetryStrategy.RETRY_SAME_SELECTOR,
                reason="retryable upstream failure with no remaining selector fallback",
                selectors=(resolved_selector,),
                selector_mode="exact",
            ),
            "retry_same_selector",
        )

    return None, "missing_resolved_selector"


def _log_alternate_strategy(
    *,
    surface: PiToolBudgetSurface,
    attempts: list[dict[str, Any]],
    next_plan: _AttemptPlan,
) -> None:
    logger.warning(
        "Retrying read-only generation with alternate strategy",
        extra={
            "surface": surface.value,
            "generation_strategy": next_plan.strategy.value,
            "strategy_reason": next_plan.reason,
            "strategy_attempts": attempts,
        },
    )


def stream_events(
    messages: list[Message],
    *,
    surface: PiToolBudgetSurface,
    settings: Settings | None = None,
    model: str | None = None,
    model_preferences: Sequence[str] | None = None,
    selector_role: str = "chat",
    thinking_level: PiThinkingLevel | None = None,
    timeout_s: float | None = None,
    tools: list[BridgeToolSpec] | None = None,
    max_tool_rounds: int | None = None,
) -> Iterator[LLMEvent]:
    """Yield bridge-backed structured events for one request."""
    settings = settings or get_settings()
    attempts: list[dict[str, Any]] = []
    attempt_plan = _AttemptPlan(strategy=ReadOnlyRetryStrategy.PRIMARY)
    attempt_index = 1
    visible_output_started = False

    while True:
        attempt_state: dict[str, Any] = {}
        try:
            for event in _stream_events_once(
                messages,
                surface=surface,
                settings=settings,
                model=model,
                model_preferences=model_preferences,
                selector_role=selector_role,
                thinking_level=thinking_level,
                timeout_s=timeout_s,
                tools=tools,
                max_tool_rounds=max_tool_rounds,
                attempt_plan=attempt_plan,
                attempt_index=attempt_index,
                attempt_state=attempt_state,
            ):
                if event["type"] == "done":
                    attempts.append(_attempt_snapshot(attempt_state=attempt_state, success=True))
                    completed = dict(event)
                    completed["strategy_attempts"] = [dict(attempt) for attempt in attempts]
                    yield completed
                    return
                visible_output_started = True
                yield event
            return
        except BridgeUpstreamError as exc:
            attempts.append(
                _attempt_snapshot(attempt_state=attempt_state, success=False, error=exc)
            )
            next_plan, exhaustion_reason = _choose_readonly_alternate(
                surface=surface,
                settings=settings,
                current_plan=attempt_plan,
                attempt_state=attempt_state,
                explicit_model=model,
                error=exc,
                visible_output_started=visible_output_started,
            )
            if next_plan is None:
                if _is_readonly_surface(surface) and exc.retryable:
                    raise ReadOnlyGenerationExhaustedError(
                        surface=surface.value,
                        attempts=attempts,
                        final_error=exc,
                        exhaustion_reason=exhaustion_reason,
                    ) from exc
                raise
            _log_alternate_strategy(surface=surface, attempts=attempts, next_plan=next_plan)
            attempt_plan = next_plan
            attempt_index += 1


def chat_completion(
    messages: list[Message],
    *,
    surface: PiToolBudgetSurface,
    settings: Settings | None = None,
    model: str | None = None,
    model_preferences: Sequence[str] | None = None,
    selector_role: str = "chat",
    thinking_level: PiThinkingLevel | None = None,
    timeout_s: float | None = None,
) -> tuple[str, dict[str, Any]]:
    settings = settings or get_settings()
    attempts: list[dict[str, Any]] = []
    attempt_plan = _AttemptPlan(strategy=ReadOnlyRetryStrategy.PRIMARY)
    attempt_index = 1

    while True:
        attempt_state: dict[str, Any] = {}
        content_parts: list[str] = []
        metadata: dict[str, Any] = {}
        try:
            for event in _stream_events_once(
                messages,
                surface=surface,
                settings=settings,
                model=model,
                model_preferences=model_preferences,
                selector_role=selector_role,
                thinking_level=thinking_level,
                timeout_s=timeout_s,
                tools=None,
                max_tool_rounds=None,
                attempt_plan=attempt_plan,
                attempt_index=attempt_index,
                attempt_state=attempt_state,
            ):
                event_type = event["type"]
                if event_type == "text_delta":
                    content_parts.append(str(event.get("delta", "")))
                elif event_type == "done":
                    attempts.append(_attempt_snapshot(attempt_state=attempt_state, success=True))
                    finalized_event = dict(event)
                    finalized_event["strategy_attempts"] = [dict(attempt) for attempt in attempts]
                    metadata = _metadata_from_done(finalized_event)
                    return "".join(content_parts), metadata
        except BridgeUpstreamError as exc:
            attempts.append(
                _attempt_snapshot(attempt_state=attempt_state, success=False, error=exc)
            )
            next_plan, exhaustion_reason = _choose_readonly_alternate(
                surface=surface,
                settings=settings,
                current_plan=attempt_plan,
                attempt_state=attempt_state,
                explicit_model=model,
                error=exc,
                visible_output_started=False,
            )
            if next_plan is None:
                if _is_readonly_surface(surface) and exc.retryable:
                    raise ReadOnlyGenerationExhaustedError(
                        surface=surface.value,
                        attempts=attempts,
                        final_error=exc,
                        exhaustion_reason=exhaustion_reason,
                    ) from exc
                raise
            _log_alternate_strategy(surface=surface, attempts=attempts, next_plan=next_plan)
            attempt_plan = next_plan
            attempt_index += 1


def stream_completion(
    messages: list[Message],
    *,
    surface: PiToolBudgetSurface,
    settings: Settings | None = None,
    model: str | None = None,
    model_preferences: Sequence[str] | None = None,
    selector_role: str = "chat",
    thinking_level: PiThinkingLevel | None = None,
    timeout_s: float | None = None,
) -> Generator[str, None, None]:
    for event in stream_events(
        messages,
        surface=surface,
        settings=settings,
        model=model,
        model_preferences=model_preferences,
        selector_role=selector_role,
        thinking_level=thinking_level,
        timeout_s=timeout_s,
    ):
        if event["type"] == "text_delta":
            delta = str(event.get("delta", ""))
            if delta:
                yield delta


def chat_with_tools(
    messages: list[Message],
    tools: list[BridgeToolSpec] | None = None,
    *,
    surface: PiToolBudgetSurface,
    settings: Settings | None = None,
    max_tool_rounds: int | None = None,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    settings = settings or get_settings()
    content_parts: list[str] = []
    metadata: dict[str, Any] = {}
    tool_calls: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []

    for event in stream_events(
        messages,
        surface=surface,
        settings=settings,
        tools=tools or get_agent_bridge_tools(),
        max_tool_rounds=max_tool_rounds,
    ):
        event_type = event["type"]
        if event_type == "text_delta":
            content_parts.append(str(event.get("delta", "")))
        elif event_type == "tool_call":
            tool_calls.append(
                {
                    "name": event.get("name"),
                    "arguments": event.get("arguments") or {},
                }
            )
        elif event_type == "tool_result":
            tool_outputs.append(
                {
                    "tool_call_id": event.get("tool_call_id"),
                    "name": event.get("name"),
                    "arguments": event.get("arguments") or {},
                    "output": event.get("output"),
                    "is_error": bool(event.get("is_error", False)),
                }
            )
        elif event_type == "done":
            metadata = _metadata_from_done(event)

    metadata["tool_outputs"] = tool_outputs
    return "".join(content_parts), metadata, tool_calls
