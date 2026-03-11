"""Feature-owned storage modules.

Purpose:
    Group persistence helpers by feature/domain instead of concentrating
    unrelated storage APIs in `cloop.db`.

Responsibilities:
    - Expose feature-owned store modules for notes, memory, interactions,
      idempotency, and scheduler state.
    - Keep transport and service code importing the owning store directly.

Non-scope:
    - Connection management or schema migration orchestration (see `cloop.db`)
    - Domain business logic outside storage concerns

Invariants/Assumptions:
    - All stores use `cloop.db.core_connection` or an explicit caller-owned
      SQLite connection.
    - Core schema DDL still lives with the infrastructure migration layer until
      the full schema extraction is complete.
"""

from .idempotency_store import claim_or_replay_idempotency, finalize_idempotency_response
from .interaction_store import record_interaction
from .memory_store import (
    create_memory_entry,
    delete_memory_entry,
    get_memory_entry,
    list_memory_entries,
    search_memory_entries,
    update_memory_entry,
)
from .notes_store import list_notes, read_note, search_notes, upsert_note
from .scheduler_store import (
    claim_scheduler_push,
    claim_task_run,
    finish_task_run,
    get_task_run,
    get_task_schedule,
    heartbeat_task_run,
    mark_abandoned_runs,
    record_scheduler_push,
    task_ready,
    update_task_schedule,
)

__all__ = [
    "claim_or_replay_idempotency",
    "claim_scheduler_push",
    "claim_task_run",
    "create_memory_entry",
    "delete_memory_entry",
    "finalize_idempotency_response",
    "finish_task_run",
    "get_task_run",
    "get_task_schedule",
    "get_memory_entry",
    "heartbeat_task_run",
    "list_memory_entries",
    "list_notes",
    "mark_abandoned_runs",
    "read_note",
    "record_scheduler_push",
    "record_interaction",
    "search_memory_entries",
    "search_notes",
    "task_ready",
    "update_memory_entry",
    "update_task_schedule",
    "upsert_note",
]
