"""Loop template management service functions.

Purpose:
    Own loop-template CRUD and template-from-loop creation so template
    management stays separate from the general loop service module.

Responsibilities:
    - Create, update, and delete loop templates
    - Create templates from existing loops through the canonical bulk helper

Non-scope:
    - Template variable substitution or application behavior
    - Generic loop lifecycle operations
    - Transport-level validation and response shaping

Invariants/Assumptions:
    - Transaction ownership stays at this module boundary for template writes
    - Template-from-loop delegates to the shared bulk implementation
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .. import typingx
from . import repo
from .bulk import create_template_from_loop as bulk_create_template_from_loop


@typingx.validate_io()
def create_loop_template(
    *,
    name: str,
    description: str | None,
    raw_text_pattern: str,
    defaults_json: dict[str, Any],
    is_system: bool = False,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a loop template within a caller-owned transaction."""
    with conn:
        return repo.create_loop_template(
            name=name,
            description=description,
            raw_text_pattern=raw_text_pattern,
            defaults_json=defaults_json,
            is_system=is_system,
            conn=conn,
        )


@typingx.validate_io()
def update_loop_template(
    *,
    template_id: int,
    name: str | None = None,
    description: str | None = None,
    raw_text_pattern: str | None = None,
    defaults_json: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a loop template within a caller-owned transaction."""
    with conn:
        return repo.update_loop_template(
            template_id=template_id,
            name=name,
            description=description,
            raw_text_pattern=raw_text_pattern,
            defaults_json=defaults_json,
            conn=conn,
        )


@typingx.validate_io()
def delete_loop_template(*, template_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a loop template within a caller-owned transaction."""
    with conn:
        return repo.delete_loop_template(template_id=template_id, conn=conn)


@typingx.validate_io()
def create_template_from_loop(
    *,
    loop_id: int,
    template_name: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a loop template from an existing loop."""
    return bulk_create_template_from_loop(
        loop_id=loop_id,
        template_name=template_name,
        conn=conn,
    )
