"""Typed exceptions for the loops subsystem.

This module provides a hierarchy of typed exceptions that replace
string-matching error detection throughout the codebase. Using typed
exceptions provides:
- Compile-time guarantees via isinstance() checks
- Clear error categories (not found, validation, transition)
- Consistent error messages across HTTP and MCP interfaces

Exception Hierarchy:
    CloopError (base)
    ├── NotFoundError (base for 404s)
    │   ├── LoopNotFoundError
    │   ├── NoteNotFoundError
    │   └── ProjectNotFoundError
    ├── ValidationError (for invalid_* errors)
    └── TransitionError (for invalid_status_transition)
"""

from __future__ import annotations

from typing import Optional


class CloopError(Exception):
    """Base exception for all Cloop domain errors."""

    def __init__(self, message: str, *, detail: Optional[str] = None) -> None:
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


class ProjectNotFoundError(NotFoundError):
    """Raised when a project with the specified ID does not exist."""

    def __init__(self, project_id: int) -> None:
        super().__init__(f"Project not found: {project_id}", detail=f"project_id={project_id}")
        self.project_id = project_id


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
