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

from ..loops import repo as loop_repo
from ..loops import template_management
from ._mutation import run_idempotent_tool_mutation
from ._runtime import with_mcp_error_handling

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


@with_mcp_error_handling
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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.list_loop_templates(conn=conn)


@with_mcp_error_handling
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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.get_loop_template(template_id=template_id, conn=conn)


@with_mcp_error_handling
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
    payload = {
        "name": name,
        "description": description,
        "raw_text_pattern": raw_text_pattern,
        "defaults": defaults,
    }
    return run_idempotent_tool_mutation(
        tool_name="loop.template.create",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: template_management.create_loop_template(
            name=name,
            description=description,
            raw_text_pattern=raw_text_pattern,
            defaults_json=defaults or {},
            is_system=False,
            conn=conn,
        ),
    )


@with_mcp_error_handling
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
    payload = {"template_id": template_id}
    return run_idempotent_tool_mutation(
        tool_name="loop.template.delete",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: {
            "deleted": template_management.delete_loop_template(
                template_id=template_id,
                conn=conn,
            )
        },
    )


@with_mcp_error_handling
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
    payload = {"loop_id": loop_id, "name": name}
    return run_idempotent_tool_mutation(
        tool_name="loop.template.from_loop",
        request_id=request_id,
        payload=payload,
        execute=lambda conn, settings: template_management.create_template_from_loop(
            loop_id=loop_id,
            template_name=name,
            conn=conn,
        ),
    )


@with_mcp_error_handling
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
    from .. import db
    from ..settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        return loop_repo.list_projects(conn=conn)


def register_loop_template_tools(mcp: "FastMCP") -> None:
    """Register loop template tools with the MCP server."""
    from ._runtime import with_db_init

    mcp.tool(name="loop.template.list")(with_db_init(loop_template_list))
    mcp.tool(name="loop.template.get")(with_db_init(loop_template_get))
    mcp.tool(name="loop.template.create")(with_db_init(loop_template_create))
    mcp.tool(name="loop.template.delete")(with_db_init(loop_template_delete))
    mcp.tool(name="loop.template.from_loop")(with_db_init(loop_template_from_loop))
    mcp.tool(name="project.list")(with_db_init(project_list))
