"""Grounded chat MCP tools.

Purpose:
    Expose grounded chat completions to MCP clients through the same shared chat
    execution contract used by HTTP and CLI surfaces.

Responsibilities:
    - Provide `chat.complete` for non-streaming grounded chat execution
    - Reuse shared chat preparation/execution and interaction logging
    - Keep MCP transport details thin by delegating to shared execution
    - Convert domain/runtime failures into MCP `ToolError` responses

Tools:
    - chat.complete: Run grounded chat with optional tool use and context injection

Non-scope:
    - Streaming transport behavior
    - MCP server assembly
    - Chat prompt/execution semantics outside the shared contract
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..chat_execution import execute_chat_request
from ..schemas.chat import ChatMessage, ChatRequest, ToolCall
from ..settings import ToolMode, get_settings
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _build_chat_request(
    *,
    messages: Sequence[ChatMessage | dict[str, Any]],
    tool_call: ToolCall | dict[str, Any] | None,
    tool_mode: ToolMode | None,
    include_loop_context: bool,
    include_memory_context: bool,
    memory_limit: int,
    include_rag_context: bool,
    rag_k: int,
    rag_scope: str | None,
) -> ChatRequest:
    normalized_messages = [
        message if isinstance(message, ChatMessage) else ChatMessage(**message)
        for message in messages
    ]
    normalized_tool_call: ToolCall | None
    if tool_call is None or isinstance(tool_call, ToolCall):
        normalized_tool_call = tool_call
    else:
        normalized_tool_call = ToolCall(**tool_call)

    return ChatRequest(
        messages=normalized_messages,
        tool_call=normalized_tool_call,
        tool_mode=tool_mode,
        include_loop_context=include_loop_context,
        include_memory_context=include_memory_context,
        memory_limit=memory_limit,
        include_rag_context=include_rag_context,
        rag_k=rag_k,
        rag_scope=rag_scope,
    )


@with_mcp_error_handling
def chat_complete(
    messages: list[ChatMessage],
    tool_call: ToolCall | None = None,
    tool_mode: ToolMode | None = None,
    include_loop_context: bool = False,
    include_memory_context: bool = False,
    memory_limit: int = 10,
    include_rag_context: bool = False,
    rag_k: int = 5,
    rag_scope: str | None = None,
) -> dict[str, Any]:
    """Run grounded chat and return the shared structured response.

    This tool reuses the same grounded chat preparation/execution contract as the
    HTTP `/chat` endpoint and `cloop chat`. It supports manual tools, bridge-led
    tool calling, loop/memory/RAG grounding, and returns the canonical chat
    response payload. MCP currently exposes the non-streaming chat contract only.

    Args:
        messages: Ordered chat transcript. Include any system/assistant/user
            messages exactly as you want them sent to the shared chat contract.
        tool_call: Optional manual tool invocation payload. Only valid when the
            effective tool mode is `manual`.
        tool_mode: Optional tool orchestration mode (`manual`, `llm`, or `none`).
            When omitted, the shared server default is used.
        include_loop_context: Inject prioritized loop context when true.
        include_memory_context: Inject stored memory entries when true.
        memory_limit: Maximum memory entries to include when memory grounding is on.
        include_rag_context: Inject retrieved document context when true.
        rag_k: Number of chunks to retrieve when RAG grounding is enabled.
        rag_scope: Optional retrieval restriction by path substring or `doc:<id>`.

    Returns:
        Dict matching the shared `ChatResponse` contract with:
        - `message`: Final assistant text
        - `tool_result`: Optional tool output payload
        - `tool_calls`: Tool calls performed during execution
        - `model` / `metadata`: Generation metadata
        - `options`: Effective resolved chat options
        - `context`: Summary of applied grounding inputs
        - `sources`: Retrieved document sources used for grounding

    Raises:
        ToolError: If request validation fails, tool usage is invalid, or chat
            execution raises a shared domain/runtime error.
    """
    settings = get_settings()
    request = _build_chat_request(
        messages=messages,
        tool_call=tool_call,
        tool_mode=tool_mode,
        include_loop_context=include_loop_context,
        include_memory_context=include_memory_context,
        memory_limit=memory_limit,
        include_rag_context=include_rag_context,
        rag_k=rag_k,
        rag_scope=rag_scope,
    )
    result = execute_chat_request(
        request=request,
        settings=settings,
        endpoint="/mcp/chat.complete",
    )
    return result.response.model_dump(mode="json")


def register_chat_tools(mcp: "FastMCP") -> None:
    """Register grounded chat tools with the MCP server."""
    from ._runtime import with_db_init

    mcp.tool(name="chat.complete")(with_db_init(chat_complete))
