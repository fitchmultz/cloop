"""Shared utility functions for loop operations.

Purpose:
    Provide common utilities used across the loops subsystem.

Responsibilities:
    - Tag normalization (single tag and batch)

Non-scope:
    - Database operations (see repo.py)
    - Business logic (see service.py)
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def normalize_tag(tag: str | None) -> str | None:
    """Normalize a single tag name.

    Applies: strip whitespace, convert to lowercase.

    Args:
        tag: Tag string to normalize, or None

    Returns:
        Normalized tag string, or None if input was None or empty after stripping
    """
    if tag is None:
        return None
    normalized = tag.strip().lower()
    return normalized if normalized else None


def normalize_tags(tags: Iterable[Any] | None) -> list[str]:
    """Normalize a collection of tag names.

    Applies: strip whitespace, convert to lowercase, filter empty strings.
    Preserves order, does NOT dedupe (callers handle deduplication as needed).

    Args:
        tags: Iterable of tag values (converted to str), or None

    Returns:
        List of normalized non-empty tag strings in original order
    """
    if tags is None:
        return []
    return [normalized for tag in tags if (normalized := str(tag).strip().lower())]
