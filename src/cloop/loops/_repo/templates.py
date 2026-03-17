"""Loop-template repository operations.

Purpose:
    Persist reusable loop templates and their default payloads.

Responsibilities:
    - Create, read, update, list, and delete templates
    - Enforce repository-level system-template constraints
    - Serialize template defaults for storage

Non-scope:
    - Template application/orchestration logic
    - Saved views or review-session metadata
    - Core loop-row CRUD outside template tables
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..errors import ValidationError


def create_loop_template(
    *,
    name: str,
    description: str | None,
    raw_text_pattern: str,
    defaults_json: dict[str, Any],
    is_system: bool = False,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a new loop template.

    Args:
        name: Template name (must be unique)
        description: Optional template description
        raw_text_pattern: Pattern text with optional {{variable}} placeholders
        defaults_json: Dictionary of default field values
        is_system: Whether this is a system template (cannot be modified)
        conn: Database connection

    Returns:
        Created template record as dict

    Raises:
        ValidationError: If name is empty or already exists
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValidationError("name", "template name cannot be empty")

    try:
        cursor = conn.execute(
            """
            INSERT INTO loop_templates (
                name, description, raw_text_pattern, defaults_json, is_system
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                normalized_name,
                description,
                raw_text_pattern,
                json.dumps(defaults_json),
                1 if is_system else 0,
            ),
        )
        template_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("name", f"template '{normalized_name}' already exists") from None

    row = conn.execute("SELECT * FROM loop_templates WHERE id = ?", (template_id,)).fetchone()
    return dict(row)


def list_loop_templates(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all loop templates, ordered by system templates first, then name.

    Args:
        conn: Database connection

    Returns:
        List of template records as dicts
    """
    rows = conn.execute("SELECT * FROM loop_templates ORDER BY is_system DESC, name ASC").fetchall()
    return [dict(row) for row in rows]


def get_loop_template(*, template_id: int, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get a template by ID.

    Args:
        template_id: Template ID
        conn: Database connection

    Returns:
        Template record as dict, or None if not found
    """
    row = conn.execute("SELECT * FROM loop_templates WHERE id = ?", (template_id,)).fetchone()
    return dict(row) if row else None


def get_loop_template_by_name(*, name: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Get a template by name (case-insensitive).

    Args:
        name: Template name to lookup
        conn: Database connection

    Returns:
        Template record as dict, or None if not found
    """
    row = conn.execute(
        "SELECT * FROM loop_templates WHERE LOWER(name) = LOWER(?)",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def update_loop_template(
    *,
    template_id: int,
    name: str | None = None,
    description: str | None = None,
    raw_text_pattern: str | None = None,
    defaults_json: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Update a loop template. System templates cannot be modified.

    Args:
        template_id: Template ID to update
        name: New name (optional)
        description: New description (optional)
        raw_text_pattern: New pattern (optional)
        defaults_json: New defaults (optional)
        conn: Database connection

    Returns:
        Updated template record

    Raises:
        ValidationError: If template not found, is a system template, or name conflict
    """
    existing = get_loop_template(template_id=template_id, conn=conn)
    if not existing:
        raise ValidationError("template_id", f"template {template_id} not found")
    if existing["is_system"]:
        raise ValidationError("template_id", "system templates cannot be modified")

    updates: dict[str, Any] = {}
    if name is not None:
        normalized = name.strip()
        if not normalized:
            raise ValidationError("name", "template name cannot be empty")
        updates["name"] = normalized
    if description is not None:
        updates["description"] = description
    if raw_text_pattern is not None:
        updates["raw_text_pattern"] = raw_text_pattern
    if defaults_json is not None:
        updates["defaults_json"] = json.dumps(defaults_json)

    if not updates:
        return existing

    set_clause = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values()) + [template_id]

    try:
        conn.execute(
            f"UPDATE loop_templates SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
    except sqlite3.IntegrityError:
        raise ValidationError(
            "name", f"template '{updates.get('name', '')}' already exists"
        ) from None

    row = conn.execute("SELECT * FROM loop_templates WHERE id = ?", (template_id,)).fetchone()
    return dict(row)


def delete_loop_template(*, template_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a loop template. System templates cannot be deleted.

    Args:
        template_id: Template ID to delete
        conn: Database connection

    Returns:
        True if deleted, False if not found

    Raises:
        ValidationError: If trying to delete a system template
    """
    existing = get_loop_template(template_id=template_id, conn=conn)
    if not existing:
        return False
    if existing["is_system"]:
        raise ValidationError("template_id", "system templates cannot be deleted")

    cursor = conn.execute("DELETE FROM loop_templates WHERE id = ?", (template_id,))
    return cursor.rowcount > 0
