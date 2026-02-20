"""Chat completion request/response models.

Purpose:
    Define Pydantic models for the /chat endpoint.

Responsibilities:
    - Chat completion request/response schemas
    - Tool execution models

Non-scope:
    - LLM provider logic (see llm.py)
    - Tool implementations (see tools.py)

Models for the /chat endpoint supporting:
- Basic chat completions
- Manual tool execution (read_note, write_note, loop_*)
- LLM-orchestrated tool mode
"""

from typing import TYPE_CHECKING, Any, Dict, List, TypedDict

from pydantic import BaseModel, Field, conlist, model_validator

from ..constants import CHAT_MESSAGE_MAX
from ..settings import ToolMode


class _InteractionMetadata(TypedDict):
    """Internal metadata for interaction logging."""

    model: str
    latency_ms: float
    usage: dict[str, Any]


class ChatMessage(BaseModel):
    """A single message in a chat conversation."""

    role: str
    content: str = Field(..., max_length=CHAT_MESSAGE_MAX)


class ToolCall(BaseModel):
    """Manual tool call instruction for chat requests.

    Supports all tools defined in TOOL_SPECS:
    - Note tools: read_note, write_note
    - Loop tools: loop_create, loop_update, loop_close, loop_list,
      loop_search, loop_next, loop_transition, loop_snooze,
      loop_enrich, loop_get
    """

    name: str = Field(..., description="Tool name from TOOL_SPECS")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific arguments matching TOOL_SPECS parameters",
    )


if TYPE_CHECKING:
    ChatMessageList = List[ChatMessage]
else:
    ChatMessageList = conlist(ChatMessage, min_length=1)


class ChatRequest(BaseModel):
    """Request for chat completion with optional tool interaction."""

    messages: ChatMessageList
    tool_call: ToolCall | None = Field(
        default=None, description="Optional instruction to interact with notes"
    )
    tool_mode: ToolMode | None = Field(
        default=None,
        description="Tool orchestration mode: manual, llm, or none. Defaults to settings.",
    )
    include_loop_context: bool = Field(
        default=False,
        description="When True, inject prioritized loop state as system context.",
    )
    include_memory_context: bool = Field(
        default=False,
        description="When True, inject relevant memory entries as system context.",
    )
    memory_limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max memory entries to include when include_memory_context is True.",
    )

    @model_validator(mode="after")
    def _manual_requires_tool(self) -> "ChatRequest":
        if self.tool_mode is ToolMode.MANUAL and self.tool_call is None:
            raise ValueError("tool_call required in manual mode")
        return self


class ChatResponse(BaseModel):
    """Response from chat completion."""

    message: str
    tool_result: Dict[str, Any] | None = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    model: str | None = None
