"""Pydantic request/response models for Cloop API.

This module provides the schema layer between HTTP boundaries and service logic.
All models use Pydantic v2 for validation and serialization.

Organization:
- chat.py: Chat completions and tool interactions
- loops.py: Loop/task management (CRUD, transitions, export/import)
- memory.py: Assistant memory store (preferences, facts, commitments)
- rag.py: Document ingestion and retrieval
- health.py: Health check responses
"""

from .chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
    _InteractionMetadata,
)
from .health import HealthResponse
from .loops import (
    LoopBase,
    LoopCaptureRequest,
    LoopCloseRequest,
    LoopExportItem,
    LoopExportResponse,
    LoopImportRequest,
    LoopImportResponse,
    LoopNextResponse,
    LoopResponse,
    LoopStatusRequest,
    LoopUpdateRequest,
)
from .memory import (
    MemoryCategory,
    MemoryCreateRequest,
    MemoryEntryBase,
    MemoryListResponse,
    MemoryResponse,
    MemorySource,
    MemoryUpdateRequest,
)
from .rag import AskResponse, FailedFileInfo, IngestMode, IngestRequest, IngestResponse

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ToolCall",
    "_InteractionMetadata",
    "HealthResponse",
    "LoopBase",
    "LoopCaptureRequest",
    "LoopCloseRequest",
    "LoopExportItem",
    "LoopExportResponse",
    "LoopImportRequest",
    "LoopImportResponse",
    "LoopNextResponse",
    "LoopResponse",
    "LoopStatusRequest",
    "LoopUpdateRequest",
    "MemoryCategory",
    "MemoryCreateRequest",
    "MemoryEntryBase",
    "MemoryListResponse",
    "MemoryResponse",
    "MemorySource",
    "MemoryUpdateRequest",
    "AskResponse",
    "FailedFileInfo",
    "IngestMode",
    "IngestRequest",
    "IngestResponse",
]
