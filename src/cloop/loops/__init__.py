"""Loop package public exports.

Purpose:
    Expose the stable loop-domain import surface for callers outside the loops
    package.
Responsibilities:
    - Re-export canonical loop models and high-level read/write helpers.
    - Keep package-level imports focused on the public facade.
Scope:
    Public imports for loop records, statuses, enrichment state, and core loop
    operations.
Usage:
    Import from ``cloop.loops`` when callers need the package facade instead of
    reaching into private modules.
Invariants/Assumptions:
    - Re-exported symbols remain the supported package-level surface.
    - Private module layout may change behind this facade without changing
      callers.
"""

from .models import EnrichmentState, LoopEventType, LoopRecord, LoopStatus
from .read_service import (
    get_loop,
    list_loops,
    list_loops_by_tag,
    list_tags,
    next_loops,
    search_loops,
)
from .service import (
    capture_loop,
    export_loops,
    import_loops,
    request_enrichment,
    transition_status,
    update_loop,
)

__all__ = [
    "EnrichmentState",
    "LoopEventType",
    "LoopRecord",
    "LoopStatus",
    "capture_loop",
    "export_loops",
    "get_loop",
    "import_loops",
    "list_loops",
    "list_loops_by_tag",
    "list_tags",
    "next_loops",
    "request_enrichment",
    "search_loops",
    "transition_status",
    "update_loop",
]
