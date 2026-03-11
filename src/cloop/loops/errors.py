"""Typed exceptions for the loops subsystem.

Purpose:
    Provide a hierarchy of typed exceptions for error handling.

Responsibilities:
    - Define domain-specific exceptions
    - Enable typed error handling without string matching

Non-scope:
    - HTTP error responses (see handlers.py)
    - Error logging (see service layer)

Typed exceptions provide:
- Compile-time guarantees via isinstance() checks
- Clear error categories (not found, validation, transition)
- Consistent error messages across HTTP and MCP interfaces

Exception Hierarchy:
    CloopError (base)
    ├── NotFoundError (base for 404s)
    │   ├── LoopNotFoundError
    │   ├── NoteNotFoundError
    │   └── MemoryNotFoundError
    ├── ValidationError (for invalid_* errors)
    └── TransitionError (for invalid_status_transition)
"""

from __future__ import annotations

from typing import Any, Mapping


class CloopError(Exception):
    """Base exception for all Cloop domain errors."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(CloopError):
    """Base exception for resource-not-found errors.

    Maps to HTTP 404 Not Found.
    """

    pass


class LoopNotFoundError(NotFoundError):
    """Raised when a loop with the specified ID does not exist."""

    def __init__(self, loop_id: int) -> None:
        super().__init__(f"Loop not found: {loop_id}", detail=f"loop_id={loop_id}")
        self.loop_id = loop_id


class NoteNotFoundError(NotFoundError):
    """Raised when a note with the specified ID does not exist."""

    def __init__(self, note_id: int) -> None:
        super().__init__(f"Note not found: {note_id}", detail=f"note_id={note_id}")
        self.note_id = note_id


class CommentNotFoundError(NotFoundError):
    """Raised when a comment with the specified ID does not exist."""

    def __init__(self, comment_id: int) -> None:
        super().__init__(f"Comment not found: {comment_id}", detail=f"comment_id={comment_id}")
        self.comment_id = comment_id


class MemoryNotFoundError(NotFoundError):
    """Raised when a memory entry with the specified ID does not exist."""

    def __init__(self, memory_id: int) -> None:
        super().__init__(f"Memory not found: {memory_id}", detail=f"memory_id={memory_id}")
        self.memory_id = memory_id


class SuggestionNotFoundError(NotFoundError):
    """Raised when a loop suggestion with the specified ID does not exist."""

    def __init__(self, suggestion_id: int) -> None:
        super().__init__(
            f"Suggestion not found: {suggestion_id}", detail=f"suggestion_id={suggestion_id}"
        )
        self.suggestion_id = suggestion_id


class ValidationError(CloopError):
    """Raised when input validation fails.

    Replaces ValueError for domain validation errors like invalid_field,
    invalid_timestamp, etc. Maps to HTTP 400 Bad Request.
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"Invalid {field}: {reason}", detail=f"field={field}")
        self.field = field
        self.reason = reason


class NoFieldsToUpdateError(CloopError):
    """Raised when a PATCH-like mutation is called without any update fields."""

    def __init__(self) -> None:
        super().__init__("no_fields_to_update", detail="field_set=empty")


class IdempotencyConflictAppError(CloopError):
    """Raised when an idempotency key is reused with a different request body."""

    def __init__(self, detail: str) -> None:
        super().__init__("Idempotency conflict", detail=detail)


class InvalidIdempotencyKeyError(CloopError):
    """Raised when an idempotency key does not meet validation rules."""

    def __init__(self, detail: str) -> None:
        super().__init__("Invalid idempotency key", detail=detail)


class ResourceNotFoundError(NotFoundError):
    """Raised when a named application resource is not found."""

    def __init__(self, resource_type: str, message: str | None = None) -> None:
        resolved_message = message or f"{resource_type.capitalize()} not found"
        super().__init__(resolved_message, detail=f"resource_type={resource_type}")
        self.resource_type = resource_type


class TransitionError(CloopError):
    """Raised when an invalid status transition is attempted.

    Maps to HTTP 400 Bad Request.
    """

    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            f"Invalid status transition: {from_status} -> {to_status}",
            detail=f"from={from_status}, to={to_status}",
        )
        self.from_status = from_status
        self.to_status = to_status


class LoopClaimedError(CloopError):
    """Raised when attempting to modify a loop claimed by another agent.

    Maps to HTTP 409 Conflict.
    """

    def __init__(self, loop_id: int, owner: str, lease_until: str) -> None:
        super().__init__(
            f"Loop {loop_id} is claimed by '{owner}' until {lease_until}",
            detail=f"loop_id={loop_id}, owner={owner}, lease_until={lease_until}",
        )
        self.loop_id = loop_id
        self.owner = owner
        self.lease_until = lease_until


class ClaimNotFoundError(CloopError):
    """Raised when a claim token doesn't match or doesn't exist.

    Maps to HTTP 404 Not Found.
    """

    def __init__(self, loop_id: int) -> None:
        super().__init__(
            f"No valid claim found for loop {loop_id}",
            detail=f"loop_id={loop_id}",
        )
        self.loop_id = loop_id


class ClaimExpiredError(CloopError):
    """Raised when attempting to renew an expired claim.

    Maps to HTTP 410 Gone.
    """

    def __init__(self, loop_id: int) -> None:
        super().__init__(
            f"Claim for loop {loop_id} has expired",
            detail=f"loop_id={loop_id}",
        )
        self.loop_id = loop_id


class RecurrenceError(CloopError):
    """Raised when recurrence configuration is invalid.

    Maps to HTTP 400 Bad Request.
    """

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message, detail=detail)


class DependencyCycleError(CloopError):
    """Raised when adding a dependency would create a cycle.

    Maps to HTTP 400 Bad Request.
    """

    def __init__(self, loop_id: int, depends_on_id: int) -> None:
        super().__init__(
            f"Cannot add dependency: loop {loop_id} -> {depends_on_id} would create a cycle",
            detail=f"loop_id={loop_id}, depends_on_id={depends_on_id}",
        )
        self.loop_id = loop_id
        self.depends_on_id = depends_on_id


class DependencyNotMetError(CloopError):
    """Raised when attempting to transition to actionable with open dependencies.

    Maps to HTTP 400 Bad Request.
    """

    def __init__(self, loop_id: int, open_dependencies: list[int]) -> None:
        super().__init__(
            f"Cannot transition loop {loop_id} to actionable: "
            f"{len(open_dependencies)} open dependencies",
            detail=f"loop_id={loop_id}, open_dependencies={open_dependencies}",
        )
        self.loop_id = loop_id
        self.open_dependencies = open_dependencies


class UndoNotPossibleError(CloopError):
    """Raised when an undo operation cannot be performed.

    Maps to HTTP 400 Bad Request.
    """

    def __init__(
        self,
        loop_id: int,
        reason: str,
        message: str,
    ) -> None:
        super().__init__(
            f"Cannot undo: {message}",
            detail=f"loop_id={loop_id}, reason={reason}",
        )
        self.loop_id = loop_id
        self.reason = reason
        self.message = message


class MergeConflictError(CloopError):
    """Raised when a merge operation cannot proceed due to conflicting state.

    Maps to HTTP 409 Conflict.
    """

    def __init__(
        self,
        loop_id: int,
        target_id: int,
        reason: str,
    ) -> None:
        super().__init__(
            f"Cannot merge loop {loop_id} into {target_id}: {reason}",
            detail=f"loop_id={loop_id}, target_id={target_id}, reason={reason}",
        )
        self.loop_id = loop_id
        self.target_id = target_id
        self.reason = reason


class LoopCreateError(CloopError):
    """Raised when a loop creation database operation fails.

    This indicates an unexpected database failure during loop insertion,
    not a validation error. Maps to HTTP 500 Internal Server Error.

    Attributes:
        raw_text: The raw_text that was being inserted (truncated for display)
    """

    def __init__(self, raw_text: str) -> None:
        truncated = raw_text[:100] + "..." if len(raw_text) > 100 else raw_text
        super().__init__(
            "Failed to create loop",
            detail=f"raw_text='{truncated}'",
        )
        self.raw_text = raw_text


class LoopImportError(CloopError):
    """Raised when a loop import database operation fails.

    This indicates an unexpected database failure during loop import,
    typically when the INSERT returns no lastrowid. Maps to HTTP 500 Internal Server Error.

    Attributes:
        payload: The import payload (truncated for display)
    """

    def __init__(self, payload: Mapping[str, Any]) -> None:
        # Safely truncate payload for error detail
        payload_str = str(dict(payload))[:200]
        super().__init__(
            "Failed to import loop",
            detail=f"payload='{payload_str}'",
        )
        self.payload = payload
