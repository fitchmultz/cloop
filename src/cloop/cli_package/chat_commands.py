"""CLI chat command handlers.

Purpose:
    Implement the terminal-facing chat command on top of the shared grounded chat
    execution contract.

Responsibilities:
    - Build `ChatRequest` payloads from CLI arguments, transcript files, and stdin
    - Invoke shared chat execution for streaming and non-streaming chat flows
    - Render text-first conversational output or full JSON payloads
    - Preserve CLI-standard error handling and exit-code behavior

Non-scope:
    - Shared chat execution semantics (owned by `chat_execution.py`)
    - HTTP/SSE transport formatting
    - Bridge subprocess lifecycle management
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..chat_execution import ChatExecutionResult, execute_chat_request, stream_chat_request
from ..schemas.chat import ChatMessage, ChatRequest, ChatResponse, ToolCall
from ..settings import Settings, ToolMode
from ._runtime import cli_error, error_handler, run_cli_action


@dataclass(slots=True, frozen=True)
class CliChatRunResult:
    """CLI-facing chat result with render hints."""

    response: ChatResponse
    streamed_text: bool


def _coerce_jsonish_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _parse_tool_arguments(args: Namespace) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    if args.tool_args_json:
        parsed = _coerce_jsonish_value(args.tool_args_json)
        if not isinstance(parsed, dict):
            raise ValueError("--tool-args-json must decode to a JSON object")
        arguments.update(parsed)

    for raw in args.tool_arg:
        if "=" not in raw:
            raise ValueError("--tool-arg must use KEY=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("--tool-arg key cannot be empty")
        arguments[key] = _coerce_jsonish_value(value)
    return arguments


def _load_messages_from_file(path: str) -> list[ChatMessage]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("--messages-file must contain a JSON array of messages")
    messages: list[ChatMessage] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"message {index} in --messages-file must be an object")
        messages.append(ChatMessage(**item))
    return messages


def _read_prompt(args: Namespace) -> str | None:
    if args.prompt == "-":
        text = sys.stdin.read()
        return text.rstrip("\n") or None
    if args.prompt is not None:
        return args.prompt
    if sys.stdin.isatty():
        return None
    text = sys.stdin.read()
    return text.rstrip("\n") or None


def _build_messages(args: Namespace) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    if args.system_message:
        messages.append(ChatMessage(role="system", content=args.system_message))
    if args.messages_file:
        messages.extend(_load_messages_from_file(args.messages_file))
    prompt = _read_prompt(args)
    if prompt is not None:
        messages.append(ChatMessage(role="user", content=prompt))
    if not messages:
        raise ValueError("provide a prompt, use --messages-file, or pipe input on stdin")
    return messages


def _resolve_tool_mode(args: Namespace) -> ToolMode:
    if args.tool and args.tool_mode not in {None, ToolMode.MANUAL.value}:
        raise ValueError("--tool may only be used with --tool-mode manual")
    if args.tool:
        return ToolMode.MANUAL
    if args.tool_arg or args.tool_args_json:
        raise ValueError("--tool-arg and --tool-args-json require --tool")
    if args.tool_mode is None:
        return ToolMode.NONE
    return ToolMode(args.tool_mode)


def _build_request(args: Namespace) -> ChatRequest:
    tool_mode = _resolve_tool_mode(args)
    tool_call: ToolCall | None = None
    if args.tool:
        tool_call = ToolCall(name=args.tool, arguments=_parse_tool_arguments(args))

    return ChatRequest(
        messages=_build_messages(args),
        tool_call=tool_call,
        tool_mode=tool_mode,
        include_loop_context=args.include_loop_context,
        include_memory_context=args.include_memory_context,
        memory_limit=args.memory_limit,
        include_rag_context=args.include_rag_context,
        rag_k=args.rag_k,
        rag_scope=args.rag_scope,
    )


def _render_tool_calls(tool_calls: list[dict[str, Any]]) -> None:
    if not tool_calls:
        return
    print("\nTool calls:")
    for tool_call in tool_calls:
        arguments = json.dumps(tool_call.get("arguments") or {}, indent=2)
        print(f"- {tool_call.get('name')}")
        for line in arguments.splitlines():
            print(f"  {line}")


def _render_tool_result(tool_result: dict[str, Any] | None) -> None:
    if tool_result is None:
        return
    print("\nTool result:")
    print(json.dumps(tool_result, indent=2))


def _render_sources(sources: list[dict[str, Any]]) -> None:
    if not sources:
        return
    print("\nSources:")
    for source in sources:
        path = source.get("document_path") or f"doc:{source.get('id')}"
        chunk = source.get("chunk_index")
        score = source.get("score")
        suffix_parts: list[str] = []
        if chunk is not None:
            suffix_parts.append(f"chunk {chunk}")
        if score is not None:
            suffix_parts.append(f"score={score}")
        suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
        print(f"- {path}{suffix}")


def _render_text_result(result: CliChatRunResult) -> None:
    response = result.response
    if not result.streamed_text:
        print(response.message)
    elif response.message:
        print()

    _render_tool_calls(response.tool_calls)
    _render_tool_result(response.tool_result)
    _render_sources(response.sources)


def _render_result(result: CliChatRunResult, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result.response.model_dump(mode="json"), indent=2))
        return
    _render_text_result(result)


def chat_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop chat`."""

    def _action() -> CliChatRunResult:
        request = _build_request(args)
        stream_enabled = settings.stream_default if args.stream is None else bool(args.stream)
        if not stream_enabled:
            result: ChatExecutionResult = execute_chat_request(
                request=request,
                settings=settings,
                endpoint="/cli/chat",
            )
            return CliChatRunResult(response=result.response, streamed_text=False)

        final_response: ChatResponse | None = None
        streamed_text = False
        for event in stream_chat_request(request=request, settings=settings, endpoint="/cli/chat"):
            if args.format == "text" and event.type == "text_delta":
                token = str(event.payload.get("token", ""))
                if token:
                    print(token, end="", flush=True)
                    streamed_text = True
            elif event.type == "done":
                final_response = ChatResponse(**event.payload)

        if final_response is None:
            raise RuntimeError("chat stream finished without a final response")
        return CliChatRunResult(response=final_response, streamed_text=streamed_text)

    return run_cli_action(
        action=_action,
        render=lambda result: _render_result(result, args.format),
        error_handlers=[
            error_handler(ValueError, lambda exc: cli_error(str(exc))),
            error_handler(OSError, lambda exc: cli_error(str(exc))),
        ],
    )
