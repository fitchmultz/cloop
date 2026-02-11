"""Tests for the typed exception hierarchy."""

from cloop.loops.errors import (
    CloopError,
    LoopNotFoundError,
    NoteNotFoundError,
    NotFoundError,
    ProjectNotFoundError,
    TransitionError,
    ValidationError,
)


class TestExceptionHierarchy:
    """Test that exception inheritance is correct."""

    def test_loop_not_found_is_not_found(self) -> None:
        exc = LoopNotFoundError(42)
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, CloopError)

    def test_note_not_found_is_not_found(self) -> None:
        exc = NoteNotFoundError(1)
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, CloopError)

    def test_project_not_found_is_not_found(self) -> None:
        exc = ProjectNotFoundError(99)
        assert isinstance(exc, NotFoundError)
        assert isinstance(exc, CloopError)

    def test_validation_error_is_cloop_error(self) -> None:
        exc = ValidationError("field", "reason")
        assert isinstance(exc, CloopError)
        assert not isinstance(exc, NotFoundError)

    def test_transition_error_is_cloop_error(self) -> None:
        exc = TransitionError("inbox", "completed")
        assert isinstance(exc, CloopError)
        assert not isinstance(exc, NotFoundError)


class TestExceptionMessages:
    """Test that exception messages are human-readable."""

    def test_loop_not_found_message(self) -> None:
        exc = LoopNotFoundError(123)
        assert "Loop not found" in str(exc)
        assert "123" in str(exc)
        assert exc.loop_id == 123

    def test_note_not_found_message(self) -> None:
        exc = NoteNotFoundError(5)
        assert "Note not found" in str(exc)
        assert "5" in str(exc)
        assert exc.note_id == 5

    def test_project_not_found_message(self) -> None:
        exc = ProjectNotFoundError(7)
        assert "Project not found" in str(exc)
        assert "7" in str(exc)
        assert exc.project_id == 7

    def test_validation_error_message(self) -> None:
        exc = ValidationError("due_at_utc", "invalid date format")
        assert "Invalid due_at_utc" in str(exc)
        assert "invalid date format" in str(exc)
        assert exc.field == "due_at_utc"
        assert exc.reason == "invalid date format"

    def test_transition_error_message(self) -> None:
        exc = TransitionError("inbox", "completed")
        assert "Invalid status transition" in str(exc)
        assert "inbox" in str(exc)
        assert "completed" in str(exc)
        assert exc.from_status == "inbox"
        assert exc.to_status == "completed"


class TestExceptionDetails:
    """Test that exception details are properly stored."""

    def test_loop_not_found_detail(self) -> None:
        exc = LoopNotFoundError(42)
        assert exc.detail == "loop_id=42"

    def test_note_not_found_detail(self) -> None:
        exc = NoteNotFoundError(99)
        assert exc.detail == "note_id=99"

    def test_project_not_found_detail(self) -> None:
        exc = ProjectNotFoundError(1)
        assert exc.detail == "project_id=1"

    def test_validation_error_detail(self) -> None:
        exc = ValidationError("status", "invalid value")
        assert exc.detail == "field=status"

    def test_transition_error_detail(self) -> None:
        exc = TransitionError("actionable", "dropped")
        assert exc.detail == "from=actionable, to=dropped"

    def test_base_cloop_error_with_detail(self) -> None:
        exc = CloopError("Something went wrong", detail="extra_info=123")
        assert exc.message == "Something went wrong"
        assert exc.detail == "extra_info=123"

    def test_base_cloop_error_without_detail(self) -> None:
        exc = CloopError("Simple error")
        assert exc.message == "Simple error"
        assert exc.detail is None
