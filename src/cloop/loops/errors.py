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
    │   └── NoteNotFoundError
    ├── ValidationError (for invalid_* errors)
    └── TransitionError (for invalid_status_transition)
"""

from __future__ import annotations


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


class ValidationError(CloopError):
    """Raised when input validation fails.

    Replaces ValueError for domain validation errors like invalid_field,
    invalid_timestamp, etc. Maps to HTTP 400 Bad Request.
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"Invalid {field}: {reason}", detail=f"field={field}")
        self.field = field
        self.reason = reason


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
