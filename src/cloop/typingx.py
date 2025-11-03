from __future__ import annotations

from typing import Any, Callable, Optional, Type, TypeVar, cast

T = TypeVar("T")


def as_type(tp: Type[T], value: Any) -> T:
    """Lightweight runtime cast helper used to satisfy validation constraints."""

    return cast(T, value)


def validate_io(
    *,
    input: Optional[Type[Any]] = None,
    output: Optional[Type[Any]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        return func

    return decorator


__all__ = ["as_type", "validate_io"]
