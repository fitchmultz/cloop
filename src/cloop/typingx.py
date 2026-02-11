import functools
import inspect
from typing import Any, Callable, TypeVar, Union, get_args, get_origin

T = TypeVar("T")


def _is_instance_of_type(value: Any, expected_type: Any) -> bool:
    """Check if value matches expected_type, handling generics and Union.

    Supports:
    - Basic types (str, int, float, etc.)
    - Any (always valid)
    - NoneType (value must be None)
    - Union[X, Y, ...] and X | Y syntax (value must match any type in union)
    - Optional[X] (equivalent to Union[X, None])
    - Generic containers (list, dict, set, tuple) - checks container type only
    - Type hints from typing module (List, Dict, etc.)
    """
    # Handle Any - always valid
    if expected_type is Any:
        return True

    # Handle None/NoneType - annotation could be None (value) or type(None)
    if expected_type is None or expected_type is type(None):
        return value is None

    # Get origin for generic types (e.g., list[str] -> list, Union[int, str] -> Union)
    origin = get_origin(expected_type)

    # Handle Union types (Union[X, Y, Z] or X | Y)
    if origin is Union:
        args = get_args(expected_type)
        return any(_is_instance_of_type(value, arg) for arg in args)

    # Handle generic containers - check container type, optionally element types
    if origin is not None:
        # Check if value is instance of the origin type
        if not isinstance(value, origin):
            return False
        # For now, we validate the container type but not element-by-element
        # This keeps validation lightweight while still catching major type errors
        return True

    # Basic type check
    try:
        return isinstance(value, expected_type)
    except TypeError:
        # Some types don't work with isinstance (e.g., TypeVar, ForwardRef)
        # In these cases, we allow the value through (conservative approach)
        return True


def validate_io() -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that validates function inputs and outputs against type hints.

    Uses inspect.signature to extract type annotations and validates:
    - All positional and keyword arguments against their parameter annotations
    - Return value against the return type annotation

    Raises TypeError with a descriptive message when validation fails.
    Functions without type hints pass through unchanged for those parameters.

    Supports:
    - Basic types (str, int, float, bool, etc.)
    - Union types (Union[X, Y] or X | Y)
    - Optional types (Optional[X] or X | None)
    - Generic containers (list[T], dict[K,V], etc.)
    - Any (always passes)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        sig = inspect.signature(func)
        # Get function name safely - some callables may not have __name__
        func_name = getattr(func, "__name__", repr(func))

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Bind arguments to parameter names
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()

            # Validate each argument against its annotation
            for param_name, param in sig.parameters.items():
                if param.annotation is inspect.Parameter.empty:
                    continue  # No annotation, skip validation

                value = bound.arguments.get(param_name)
                if not _is_instance_of_type(value, param.annotation):
                    raise TypeError(
                        f"{func_name}(): argument '{param_name}' "
                        f"expected {param.annotation}, got {type(value).__name__}"
                    )

            # Call the function
            result = func(*args, **kwargs)

            # Validate return value
            if sig.return_annotation is not inspect.Signature.empty:
                if not _is_instance_of_type(result, sig.return_annotation):
                    raise TypeError(
                        f"{func_name}(): return value "
                        f"expected {sig.return_annotation}, got {type(result).__name__}"
                    )

            return result

        return wrapper

    return decorator


def escape_like_pattern(query: str) -> str:
    """Escape SQL LIKE wildcards in user input.

    Escapes % and _ characters so they are treated literally in LIKE queries.
    Uses backslash as the escape character. The backslash itself is escaped first
    to prevent double-escaping issues.

    Example:
        >>> escape_like_pattern("50% off")
        '50\\% off'
        >>> escape_like_pattern("test_file")
        'test\\_file'
    """
    # First escape the escape character itself, then % and _
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["validate_io", "escape_like_pattern"]
