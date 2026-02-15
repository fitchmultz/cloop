"""LLM chat completion and tool execution via litellm.

Purpose:
    Provide chat completion with optional tool calling for AI workflows.

Responsibilities:
    - Call litellm.completion() with provider resolution
    - Execute tool calls and return results
    - Stream completions for real-time responses

Non-scope:
    - Embedding generation (see embeddings.py)
    - Loop enrichment prompt construction (see loops/enrichment.py)

Entrypoints:
    - chat_completion(messages, settings) -> Tuple[str, Dict]
    - stream_completion(messages, settings) -> Generator
    - chat_with_tools(messages, tools, settings) -> Tuple[str, Dict, List[Dict]]
"""

import json
import time
from copy import deepcopy
from typing import Any, Dict, Generator, Iterable, List, Tuple, cast

import litellm

from .providers import resolve_provider_kwargs
from .settings import Settings, get_settings
from .tools import EXECUTORS, TOOL_SPECS, normalize_tool_arguments

Message = Dict[str, Any]


class ToolCallError(ValueError):
    """Raised when LLM-specified tool calls are invalid."""


def estimate_tokens(messages: List[Message]) -> int:
    return sum(len((message.get("content") or "").split()) for message in messages)


def chat_completion(
    messages: List[Message],
    *,
    settings: Settings | None = None,
) -> Tuple[str, Dict[str, Any]]:
    settings = settings or get_settings()
    provider_kwargs = resolve_provider_kwargs(settings.llm_model, settings)
    start = time.time()
    response = cast(
        Dict[str, Any],
        litellm.completion(
            model=settings.llm_model,
            messages=messages,
            timeout=int(settings.llm_timeout),
            **provider_kwargs,
        ),
    )
    latency_ms = (time.time() - start) * 1000
    choices = cast(List[Dict[str, Any]], response.get("choices", []))
    content = ""
    if choices:
        message = cast(Dict[str, Any], choices[0].get("message", {}))
        content = str(message.get("content", ""))
    metadata = {
        "latency_ms": latency_ms,
        "model": response.get("model") or settings.llm_model,
        "usage": response.get("usage", {}),
    }
    return content, metadata


def stream_completion(
    messages: List[Message],
    *,
    settings: Settings | None = None,
) -> Generator[str, None, None]:
    settings = settings or get_settings()
    provider_kwargs = resolve_provider_kwargs(settings.llm_model, settings)
    stream = litellm.completion(
        model=settings.llm_model,
        messages=messages,
        timeout=int(settings.llm_timeout),
        stream=True,
        **provider_kwargs,
    )
    for chunk in cast(Iterable[Any], stream):
        if isinstance(chunk, str):
            if chunk:
                yield chunk
            continue
        choice_list = cast(List[Dict[str, Any]], chunk.get("choices", []))
        if not choice_list:
            continue
        delta = cast(Dict[str, Any], choice_list[0].get("delta", {}))
        token = delta.get("content")
        if token:
            yield str(token)


def chat_with_tools(
    messages: List[Message],
    tools: List[Dict[str, Any]] | None = None,
    *,
    tool_choice: str = "auto",
    settings: Settings | None = None,
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    settings = settings or get_settings()
    tools = tools or TOOL_SPECS
    request_messages = deepcopy(messages)
    provider_kwargs = resolve_provider_kwargs(settings.llm_model, settings)

    start = time.time()
    first_response = cast(
        Dict[str, Any],
        litellm.completion(
            model=settings.llm_model,
            messages=request_messages,
            tools=tools,
            tool_choice=tool_choice,
            timeout=int(settings.llm_timeout),
            **provider_kwargs,
        ),
    )
    latency_ms = (time.time() - start) * 1000
    choices = cast(List[Dict[str, Any]], first_response.get("choices", []))
    first_message = cast(Dict[str, Any], choices[0].get("message", {})) if choices else {}
    tool_calls = cast(List[Dict[str, Any]], first_message.get("tool_calls") or [])

    normalized_calls: List[Dict[str, Any]] = []
    tool_outputs: List[Dict[str, Any]] = []

    if not tool_calls:
        content = str(first_message.get("content", ""))
        metadata = {
            "latency_ms": latency_ms,
            "model": first_response.get("model") or settings.llm_model,
            "usage": first_response.get("usage", {}),
            "tool_outputs": tool_outputs,
        }
        return content, metadata, normalized_calls

    assistant_entry: Dict[str, Any] = {
        "role": first_message.get("role", "assistant"),
    }
    if "content" in first_message:
        assistant_entry["content"] = first_message["content"]
    if "tool_calls" in first_message:
        assistant_entry["tool_calls"] = first_message["tool_calls"]

    augmented_messages = request_messages + [assistant_entry]

    for call in tool_calls:
        function_payload = cast(Dict[str, Any], call.get("function") or {})
        name = cast(str, function_payload.get("name"))
        if not name:
            continue
        try:
            arguments = normalize_tool_arguments(function_payload.get("arguments", {}))
        except ValueError as exc:
            raise ToolCallError(f"Invalid arguments for tool '{name}'") from exc
        executor = EXECUTORS.get(name)
        if executor is None:
            raise ToolCallError(f"Unsupported tool: {name}")
        try:
            result = executor(**arguments)
        except ValueError as exc:
            raise ToolCallError(str(exc)) from exc
        normalized_calls.append({"name": name, "arguments": arguments})
        tool_outputs.append(result)
        augmented_messages.append(
            {
                "role": "tool",
                "tool_call_id": call.get("id"),
                "name": name,
                "content": json.dumps(result),
            }
        )

    second_start = time.time()
    second_response = cast(
        Dict[str, Any],
        litellm.completion(
            model=settings.llm_model,
            messages=augmented_messages,
            tools=tools,
            tool_choice="none",
            timeout=int(settings.llm_timeout),
            **provider_kwargs,
        ),
    )
    latency_ms += (time.time() - second_start) * 1000
    second_choices = cast(List[Dict[str, Any]], second_response.get("choices", []))
    second_message = (
        cast(Dict[str, Any], second_choices[0].get("message", {})) if second_choices else {}
    )
    final_content = str(second_message.get("content", ""))

    metadata = {
        "latency_ms": latency_ms,
        "model": second_response.get("model") or first_response.get("model") or settings.llm_model,
        "usage": {
            "initial": first_response.get("usage", {}),
            "follow_up": second_response.get("usage", {}),
        },
        "tool_outputs": tool_outputs,
    }
    return final_content, metadata, normalized_calls
