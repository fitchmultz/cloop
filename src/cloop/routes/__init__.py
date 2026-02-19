"""FastAPI route modules for Cloop API.

Each module exports an APIRouter that can be mounted on the main app:
- chat.py: /chat endpoint
- loops.py: /loops/* endpoints
- memory.py: /memory/* endpoints
- rag.py: /ingest and /ask endpoints
"""

from .chat import router as chat_router
from .loops import router as loops_router
from .memory import router as memory_router
from .rag import router as rag_router

__all__ = ["chat_router", "loops_router", "memory_router", "rag_router"]
