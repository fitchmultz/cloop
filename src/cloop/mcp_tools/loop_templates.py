"""Loop template MCP tools.

Purpose:
    MCP tools for managing loop templates.

Responsibilities:
    - Provide CRUD operations for loop templates
    - Support template creation from existing loops
    - List projects associated with loops
    - Handle idempotency for template mutations

Tools:
    - loop.template.list: List all templates
    - loop.template.get: Get a template by ID
    - loop.template.create: Create a new template
    - loop.template.delete: Delete a template
    - loop.template.from_loop: Create template from existing loop
    - project.list: List all projects

Non-scope:
    - Template persistence (see loops/repo.py)
    - Template application (handled client-side)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp.exceptions import ToolError

from .. import db
from ..idempotency import (
    build_mcp_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ..loops import repo as loop_repo
from ..loops import service as loop_service
from ..settings import get_settings

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _handle_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    settings: Any,
) -> dict[str, Any] | None:
    """Handle idempotency for MCP tool calls."""
    from ..idempotency import IdempotencyConflictError

    if request_id is None:
        return None

    try:
        key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    except ValueError as e:
        raise ToolError(str(e)) from None

    scope = build_mcp_scope(tool_name)
    request_hash = canonical_request_hash(payload)
    expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

    with db.core_connection(settings) as conn:
        try:
            claim = db.claim_or_replay_idempotency(
                scope=scope,
                idempotency_key=key,
                request_hash=request_hash,
                expires_at=expires_at,
                conn=conn,
            )
        except IdempotencyConflictError as e:
            raise ToolError(f"Idempotency conflict: {e}") from None

        if not claim["is_new"] and claim["replay"]:
            return claim["replay"]["response_body"]

        return None


def _finalize_mcp_idempotency(
    *,
    tool_name: str,
    request_id: str | None,
    payload: dict[str, Any],
    response: dict[str, Any],
    settings: Any,
) -> None:
    """Store response for idempotent MCP tool call."""
    if request_id is None:
        return

    key = normalize_idempotency_key(request_id, settings.idempotency_max_key_length)
    scope = build_mcp_scope(tool_name)

    with db.core_connection(settings) as conn:
        db.finalize_idempotency_response(
            scope=scope,
            idempotency_key=key,
            response_status=200,
            response_body=response,
            conn=conn,
        )


def loop_template_list() -> list[dict[str, Any]]:
    """List all loop templates.

    Returns both user-created and system templates. System templates are
    built-in patterns that cannot be deleted. User templates can be created
    from scratch or derived from existing loops.

    Returns:
        List of template dicts, each with:
        - id: Unique template identifier
        - name: Template name
        - description: Optional template description
        - raw_text_pattern: Pattern with optional {{variable}} placeholders
        - defaults_json: Default field values for new loops
        - is_system: True for built-in templates, False for user-created
        - created_at_utc: When the template was created
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.list_loop_templates(conn=conn)


def loop_template_get(template_id: int) -> dict[str, Any] | None:
    """Get a template by its ID.

    Retrieves the full details of a specific template including its pattern,
    defaults, and metadata.

    Args:
        template_id: The unique identifier of the template to retrieve.

    Returns:
        Template dict with id, name, description, raw_text_pattern,
        defaults_json, is_system, and created_at_utc, or None if not found.
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.get_loop_template(template_id=template_id, conn=conn)


def loop_template_create(
    name: str,
    description: str | None = None,
    raw_text_pattern: str = "",
    defaults: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a new loop template.

    Templates provide reusable patterns for creating loops with pre-filled
    fields. Use {{variable}} placeholders in raw_text_pattern to create
    dynamic templates that prompt for values when applied.

    Args:
        name: Template name (must be unique, case-insensitive).
        description: Optional human-readable description of the template's
            purpose and usage.
        raw_text_pattern: Pattern with optional {{variable}} placeholders
            that will be replaced when the template is applied.
        defaults: Default field values (tags, time_minutes, next_action,
            project_id, etc.) to apply to loops created from this template.
        request_id: Optional idempotency key for safe retries.

    Returns:
        The created template record with id, name, description,
        raw_text_pattern, defaults_json, is_system, and created_at_utc.

    Raises:
        ToolError: If name is already in use or validation fails.
    """
    settings = get_settings()
    payload = {
        "name": name,
        "description": description,
        "raw_text_pattern": raw_text_pattern,
        "defaults": defaults,
    }

    replay = _handle_mcp_idempotency(
        tool_name="loop.template.create",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        template = loop_repo.create_loop_template(
            name=name,
            description=description,
            raw_text_pattern=raw_text_pattern,
            defaults_json=defaults or {},
            is_system=False,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.template.create",
        request_id=request_id,
        payload=payload,
        response=template,
        settings=settings,
    )
    return template


def loop_template_delete(
    template_id: int,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Delete a loop template permanently.

    Permanently removes a user-created template. System templates
    (is_system=True) cannot be deleted. This operation cannot be undone.

    Args:
        template_id: The unique identifier of the template to delete.
        request_id: Optional idempotency key for safe retries.

    Returns:
        Dict with deleted: True if the template was deleted, or deleted: False
        if the template was not found or is a system template.

    Raises:
        ToolError: If the template is a system template (cannot be deleted).
    """
    settings = get_settings()
    payload = {"template_id": template_id}

    replay = _handle_mcp_idempotency(
        tool_name="loop.template.delete",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        deleted = loop_repo.delete_loop_template(template_id=template_id, conn=conn)

    result = {"deleted": deleted}
    _finalize_mcp_idempotency(
        tool_name="loop.template.delete",
        request_id=request_id,
        payload=payload,
        response=result,
        settings=settings,
    )
    return result


def loop_template_from_loop(
    loop_id: int,
    name: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Create a template from an existing loop.

    Extracts the raw_text, tags, time_minutes, next_action, and other
    fields from an existing loop to create a reusable template. The
    template can then be used to quickly create similar loops.

    Args:
        loop_id: The unique identifier of the loop to use as template source.
        name: Name for the new template (must be unique, case-insensitive).
        request_id: Optional idempotency key for safe retries.

    Returns:
        The created template record with id, name, description,
        raw_text_pattern, defaults_json, is_system, and created_at_utc.

    Raises:
        ToolError: If the source loop is not found or name is already in use.
    """
    settings = get_settings()
    payload = {"loop_id": loop_id, "name": name}

    replay = _handle_mcp_idempotency(
        tool_name="loop.template.from_loop",
        request_id=request_id,
        payload=payload,
        settings=settings,
    )
    if replay is not None:
        return replay

    with db.core_connection(settings) as conn:
        template = loop_service.create_template_from_loop(
            loop_id=loop_id,
            template_name=name,
            conn=conn,
        )

    _finalize_mcp_idempotency(
        tool_name="loop.template.from_loop",
        request_id=request_id,
        payload=payload,
        response=template,
        settings=settings,
    )
    return template


def project_list() -> list[dict[str, Any]]:
    """List all projects.

    Returns all projects that have been associated with loops, ordered
    by name. Projects are auto-created when referenced in loop captures.

    Returns:
        List of project dicts, each with:
        - id: Unique project identifier
        - name: Project name
        - created_at_utc: When the project was created
    """
    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.list_projects(conn=conn)


def register_loop_template_tools(mcp: "FastMCP") -> None:
    """Register loop template tools with the MCP server."""
    from ..mcp_server import with_db_init, with_mcp_error_handling

    mcp.tool(name="loop.template.list")(with_db_init(with_mcp_error_handling(loop_template_list)))
    mcp.tool(name="loop.template.get")(with_db_init(with_mcp_error_handling(loop_template_get)))
    mcp.tool(name="loop.template.create")(
        with_db_init(with_mcp_error_handling(loop_template_create))
    )
    mcp.tool(name="loop.template.delete")(
        with_db_init(with_mcp_error_handling(loop_template_delete))
    )
    mcp.tool(name="loop.template.from_loop")(
        with_db_init(with_mcp_error_handling(loop_template_from_loop))
    )
    mcp.tool(name="project.list")(with_db_init(with_mcp_error_handling(project_list)))
