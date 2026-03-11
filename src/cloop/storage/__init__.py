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
    acquire_task_lease,
    get_task_run_state,
    heartbeat_task_lease,
    release_task_lease,
    renew_task_lease,
    task_due,
    update_task_run_state,
)

__all__ = [
    "acquire_task_lease",
    "claim_or_replay_idempotency",
    "create_memory_entry",
    "delete_memory_entry",
    "finalize_idempotency_response",
    "get_memory_entry",
    "get_task_run_state",
    "heartbeat_task_lease",
    "list_memory_entries",
    "list_notes",
    "read_note",
    "record_interaction",
    "release_task_lease",
    "renew_task_lease",
    "search_memory_entries",
    "search_notes",
    "task_due",
    "update_memory_entry",
    "update_task_run_state",
    "upsert_note",
]
