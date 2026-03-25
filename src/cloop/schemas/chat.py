"""Chat completion request/response models.

Purpose:
    Define the canonical transport models for the /chat endpoint.

Responsibilities:
    - Chat completion request/response schemas
    - Tool execution models
    - Client-facing response metadata, options, and grounding summaries

Non-scope:
    - LLM provider logic (see llm.py)
    - Tool implementations (see tools.py)
"""

from typing import TYPE_CHECKING, Annotated, Any, Self, TypedDict

from pydantic import BaseModel, Field, computed_field, model_validator

from ..constants import CHAT_MESSAGE_MAX
from ..settings import ToolMode
from ._loops.continuity import ContinuityRerunAction


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
    """Manual tool call instruction for chat requests."""

    name: str = Field(..., description="Tool name from TOOL_SPECS")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific arguments matching TOOL_SPECS parameters",
    )


if TYPE_CHECKING:
    ChatMessageList = list[ChatMessage]
else:
    ChatMessageList = Annotated[list[ChatMessage], Field(min_length=1)]


class ChatRequest(BaseModel):
    """Request for chat completion with optional tool interaction."""

    messages: ChatMessageList
    tool_call: ToolCall | None = Field(
        default=None,
        description="Optional instruction to interact with notes or loops in manual mode.",
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
    include_rag_context: bool = Field(
        default=False,
        description="When True, retrieve relevant document chunks and inject as context.",
    )
    rag_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of chunks to retrieve when include_rag_context is True.",
    )
    rag_scope: str | None = Field(
        default=None,
        description="Optional scope filter for retrieval (path substring or doc:ID).",
    )

    @model_validator(mode="after")
    def _manual_requires_tool(self) -> Self:
        if self.tool_mode is ToolMode.MANUAL and self.tool_call is None:
            raise ValueError("tool_call required in manual mode")
        return self


class ChatMetadataResponse(BaseModel):
    """Execution metadata returned to chat clients."""

    latency_ms: float | None = None
    model: str | None = None
    provider: str | None = None
    api: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str | None = None
    requested_selector: str | None = None
    requested_selectors: list[str] = Field(default_factory=list)
    resolved_selector: str | None = None
    fallback_used: bool = False
    selector_mode: str | None = None
    generation_strategy: str = "primary"
    alternate_strategy_used: bool = False
    strategy_reason: str | None = None
    strategy_attempts: list[dict[str, Any]] = Field(default_factory=list)


class ChatOptionsResponse(BaseModel):
    """Effective request options after applying server defaults."""

    tool_mode: ToolMode
    include_loop_context: bool
    include_memory_context: bool
    memory_limit: int
    include_rag_context: bool
    rag_k: int
    rag_scope: str | None = None


class ChatContextResponse(BaseModel):
    """Summary of which grounding context was actually applied."""

    loop_context_applied: bool = False
    memory_context_applied: bool = False
    memory_entries_used: int = 0
    rag_context_applied: bool = False
    rag_chunks_used: int = 0


class ChatResponse(BaseModel):
    """Response from chat completion."""

    message: str
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = None
    metadata: ChatMetadataResponse | None = None
    options: ChatOptionsResponse
    context: ChatContextResponse = Field(default_factory=ChatContextResponse)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    rerun_action: ContinuityRerunAction | None = None

    @computed_field
    @property
    def tool_result(self) -> dict[str, Any] | None:
        """Transitional compatibility alias for the first tool result."""
        return self.tool_results[0] if self.tool_results else None
