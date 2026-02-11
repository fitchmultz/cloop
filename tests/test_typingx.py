"""Tests for typingx module."""

import sqlite3
from typing import Any, Optional, Union

import pytest

from cloop import typingx
from cloop.loops.models import LoopStatus


class TestValidateIO:
    """Tests for validate_io decorator."""

    def test_validates_input_types_basic(self) -> None:
        """Should raise TypeError when input type doesn't match."""

        @typingx.validate_io()
        def process(name: str, count: int) -> str:
            return f"{name}: {count}"

        # Valid call should work
        assert process("test", 42) == "test: 42"

        # Invalid input type should raise TypeError
        with pytest.raises(TypeError, match="argument 'count' expected"):
            process("test", "not an int")

    def test_validates_input_types_string(self) -> None:
        """Should raise TypeError when string type doesn't match."""

        @typingx.validate_io()
        def greet(name: str) -> str:
            return f"Hello, {name}"

        # Valid call
        assert greet("Alice") == "Hello, Alice"

        # Invalid - passing int instead of str
        with pytest.raises(TypeError, match="argument 'name' expected"):
            greet(123)

    def test_validates_output_types(self) -> None:
        """Should raise TypeError when return type doesn't match."""

        @typingx.validate_io()
        def get_name() -> str:
            return 123  # type: ignore[return-value]

        with pytest.raises(TypeError, match="return value expected"):
            get_name()

    def test_optional_types_with_value(self) -> None:
        """Should handle Optional[T] correctly with a value."""

        @typingx.validate_io()
        def maybe_value(x: Optional[str]) -> Optional[int]:
            if x is None:
                return None
            return len(x)

        assert maybe_value("hello") == 5

    def test_optional_types_with_none(self) -> None:
        """Should handle Optional[T] correctly with None."""

        @typingx.validate_io()
        def maybe_value(x: Optional[str]) -> Optional[int]:
            if x is None:
                return None
            return len(x)

        assert maybe_value(None) is None

    def test_optional_input_validation_failure(self) -> None:
        """Should reject wrong type even in Optional."""

        @typingx.validate_io()
        def process(x: Optional[int]) -> str:
            return str(x) if x is not None else "none"

        # Valid calls
        assert process(42) == "42"
        assert process(None) == "none"

        # Invalid - wrong type
        with pytest.raises(TypeError, match="argument 'x' expected"):
            process("string")

    def test_union_types(self) -> None:
        """Should handle Union types correctly."""

        @typingx.validate_io()
        def union_func(x: Union[str, int]) -> str:
            return str(x)

        assert union_func("test") == "test"
        assert union_func(42) == "42"

    def test_union_type_validation_failure(self) -> None:
        """Should reject values not in Union."""

        @typingx.validate_io()
        def union_func(x: Union[str, int]) -> str:
            return str(x)

        # Invalid - list not in Union[str, int]
        with pytest.raises(TypeError, match="argument 'x' expected"):
            union_func([1, 2, 3])

    def test_union_return_type(self) -> None:
        """Should validate Union return types."""

        @typingx.validate_io()
        def get_value(return_int: bool) -> Union[str, int]:
            if return_int:
                return 42
            return "string"

        assert get_value(True) == 42
        assert get_value(False) == "string"

    def test_union_return_type_failure(self) -> None:
        """Should reject wrong Union return type."""

        @typingx.validate_io()
        def get_bad_value() -> Union[str, int]:
            return [1, 2, 3]  # type: ignore[return-value]

        with pytest.raises(TypeError, match="return value expected"):
            get_bad_value()

    def test_no_annotation_skips_validation(self) -> None:
        """Should not validate parameters without type annotations."""

        @typingx.validate_io()
        def no_types(x, y):
            return x + y

        # Should work with any types since no annotations
        assert no_types(1, 2) == 3
        assert no_types("a", "b") == "ab"

    def test_partial_annotations(self) -> None:
        """Should validate only annotated parameters."""

        @typingx.validate_io()
        def partial(x: int, y):
            return x + (y if isinstance(y, int) else 0)

        # Valid - x is int, y can be anything
        assert partial(1, 2) == 3
        assert partial(1, "anything") == 1

        # Invalid - x must be int
        with pytest.raises(TypeError, match="argument 'x' expected"):
            partial("not int", 2)

    def test_list_type(self) -> None:
        """Should validate list container type."""

        @typingx.validate_io()
        def process_list(items: list[str]) -> int:
            return len(items)

        assert process_list(["a", "b"]) == 2

        # Invalid - not a list
        with pytest.raises(TypeError, match="argument 'items' expected"):
            process_list("not a list")

    def test_dict_type(self) -> None:
        """Should validate dict container type."""

        @typingx.validate_io()
        def process_dict(data: dict[str, int]) -> int:
            return sum(data.values())

        assert process_dict({"a": 1, "b": 2}) == 3

        # Invalid - not a dict
        with pytest.raises(TypeError, match="argument 'data' expected"):
            process_dict([("a", 1)])

    def test_any_type_always_valid(self) -> None:
        """Should allow Any type to pass any value."""

        @typingx.validate_io()
        def process_any(x: Any) -> str:
            return str(x)

        # Any should accept any type
        assert process_any(1) == "1"
        assert process_any("string") == "string"
        assert process_any([1, 2, 3]) == "[1, 2, 3]"
        assert process_any(None) == "None"

    def test_any_return_type(self) -> None:
        """Should allow Any return type to return any value."""

        @typingx.validate_io()
        def get_any(return_type: str) -> Any:
            if return_type == "int":
                return 42
            elif return_type == "list":
                return [1, 2, 3]
            return "string"

        assert get_any("int") == 42
        assert get_any("list") == [1, 2, 3]

    def test_bool_type(self) -> None:
        """Should validate bool type correctly."""

        @typingx.validate_io()
        def process_flag(flag: bool) -> str:
            return "yes" if flag else "no"

        assert process_flag(True) == "yes"
        assert process_flag(False) == "no"

        # Invalid - int is not bool (even though bool is subclass of int)
        # Note: In Python, isinstance(True, int) is True, so this is a quirk
        # But bool is a separate type annotation
        with pytest.raises(TypeError, match="argument 'flag' expected"):
            process_flag(1)

    def test_float_type(self) -> None:
        """Should validate float type correctly."""

        @typingx.validate_io()
        def process_float(value: float) -> float:
            return value * 2

        assert process_float(3.14) == 6.28

        # Invalid - string instead of float
        with pytest.raises(TypeError, match="argument 'value' expected"):
            process_float("3.14")

    def test_preserve_function_metadata(self) -> None:
        """Should preserve function name and docstring."""

        @typingx.validate_io()
        def my_function(x: int) -> str:
            """My docstring."""
            return str(x)

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_complex_service_function(self) -> None:
        """Test with actual service function signatures."""

        @typingx.validate_io()
        def capture_loop(
            *,
            raw_text: str,
            captured_at_iso: str,
            client_tz_offset_min: int,
            status: LoopStatus,
            conn: sqlite3.Connection,
        ) -> dict[str, Any]:
            return {"raw_text": raw_text, "status": status.value}

        # Create a mock connection
        conn = sqlite3.connect(":memory:")

        # Valid call
        result = capture_loop(
            raw_text="test",
            captured_at_iso="2024-01-01T00:00:00",
            client_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        assert result["raw_text"] == "test"

        # Invalid - wrong status type
        with pytest.raises(TypeError):
            capture_loop(
                raw_text="test",
                captured_at_iso="2024-01-01T00:00:00",
                client_tz_offset_min=0,
                status="invalid",  # Should be LoopStatus
                conn=conn,
            )

        conn.close()

    def test_service_function_with_optional(self) -> None:
        """Test service function with optional parameters."""

        @typingx.validate_io()
        def list_loops(
            *,
            status: LoopStatus | None,
            limit: int,
            conn: sqlite3.Connection,
        ) -> list[dict[str, Any]]:
            return []

        conn = sqlite3.connect(":memory:")

        # Valid with status
        assert list_loops(status=LoopStatus.INBOX, limit=10, conn=conn) == []

        # Valid with None
        assert list_loops(status=None, limit=10, conn=conn) == []

        # Invalid - wrong status type
        with pytest.raises(TypeError, match="argument 'status' expected"):
            list_loops(status="inbox", limit=10, conn=conn)

        conn.close()

    def test_list_return_type(self) -> None:
        """Should validate list return type."""

        @typingx.validate_io()
        def get_items() -> list[str]:
            return ["a", "b"]

        assert get_items() == ["a", "b"]

    def test_list_return_type_failure(self) -> None:
        """Should reject wrong list return type."""

        @typingx.validate_io()
        def get_bad_items() -> list[str]:
            return "not a list"  # type: ignore[return-value]

        with pytest.raises(TypeError, match="return value expected"):
            get_bad_items()

    def test_dict_return_type(self) -> None:
        """Should validate dict return type."""

        @typingx.validate_io()
        def get_data() -> dict[str, int]:
            return {"a": 1}

        assert get_data() == {"a": 1}

    def test_dict_return_type_failure(self) -> None:
        """Should reject wrong dict return type."""

        @typingx.validate_io()
        def get_bad_data() -> dict[str, int]:
            return [("a", 1)]  # type: ignore[return-value]

        with pytest.raises(TypeError, match="return value expected"):
            get_bad_data()

    def test_no_return_annotation(self) -> None:
        """Should not validate return if no annotation."""

        @typingx.validate_io()
        def no_return_type(x: int):
            return str(x)

        # Should work even though it returns str not int
        assert no_return_type(42) == "42"

    def test_none_return_type(self) -> None:
        """Should validate None return type."""

        @typingx.validate_io()
        def return_none() -> None:
            return None

        assert return_none() is None

    def test_none_return_type_failure(self) -> None:
        """Should reject non-None when None return type specified."""

        @typingx.validate_io()
        def return_bad_none() -> None:
            return "not none"  # type: ignore[return-value]

        with pytest.raises(TypeError, match="return value expected"):
            return_bad_none()

    def test_keyword_only_args(self) -> None:
        """Should validate keyword-only arguments."""

        @typingx.validate_io()
        def kw_only(*, x: int, y: str) -> str:
            return f"{x}-{y}"

        assert kw_only(x=1, y="test") == "1-test"

        with pytest.raises(TypeError, match="argument 'x' expected"):
            kw_only(x="not int", y="test")

    def test_positional_and_keyword_args(self) -> None:
        """Should validate both positional and keyword arguments."""

        @typingx.validate_io()
        def mixed(a: int, b: str, *, c: float) -> str:
            return f"{a}-{b}-{c}"

        # Valid positional and keyword
        assert mixed(1, "two", c=3.0) == "1-two-3.0"

        # Valid all keyword
        assert mixed(a=1, b="two", c=3.0) == "1-two-3.0"

        # Invalid positional
        with pytest.raises(TypeError, match="argument 'a' expected"):
            mixed("not int", "two", c=3.0)

        # Invalid keyword-only
        with pytest.raises(TypeError, match="argument 'c' expected"):
            mixed(1, "two", c="not float")


class TestAsType:
    """Tests for as_type helper."""

    def test_casts_value(self) -> None:
        """Should cast value to expected type."""
        value: object = "hello"
        result = typingx.as_type(str, value)
        assert result == "hello"

    def test_returns_value_unchanged(self) -> None:
        """Should return value unchanged (runtime cast only)."""
        value = 42
        result = typingx.as_type(int, value)
        assert result == 42

    def test_with_complex_type(self) -> None:
        """Should work with complex types."""
        value: object = ["a", "b", "c"]
        result = typingx.as_type(list[str], value)
        assert result == ["a", "b", "c"]
