"""Loop template endpoints.

Purpose:
    HTTP endpoints for managing loop templates.

Endpoints:
- GET /templates: List all templates
- GET /templates/{template_id}: Get a single template
- POST /templates: Create a new template
- PATCH /templates/{template_id}: Update a template
- DELETE /templates/{template_id}: Delete a template
- POST /{loop_id}/save-as-template: Create template from an existing loop
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ... import db
from ...loops.errors import LoopNotFoundError, ValidationError
from ...loops.repo import (
    create_loop_template,
    delete_loop_template,
    get_loop_template,
    list_loop_templates,
    update_loop_template,
)
from ...loops.service import create_template_from_loop
from ...schemas.loops import (
    LoopTemplateCreateRequest,
    LoopTemplateListResponse,
    LoopTemplateResponse,
    LoopTemplateUpdateRequest,
)
from ._common import IdempotencyKeyHeader, SettingsDep

router = APIRouter()


def _template_to_response(template: dict[str, Any]) -> LoopTemplateResponse:
    """Convert a template database record to a response model."""
    return LoopTemplateResponse(
        id=template["id"],
        name=template["name"],
        description=template["description"],
        raw_text_pattern=template["raw_text_pattern"],
        defaults=json.loads(template["defaults_json"]) if template["defaults_json"] else {},
        is_system=bool(template["is_system"]),
        created_at=template["created_at"],
        updated_at=template["updated_at"],
    )


@router.get("/templates", response_model=LoopTemplateListResponse)
def list_templates_endpoint(settings: SettingsDep) -> LoopTemplateListResponse:
    """List all loop templates."""
    with db.core_connection(settings) as conn:
        templates = list_loop_templates(conn=conn)

    return LoopTemplateListResponse(templates=[_template_to_response(t) for t in templates])


@router.get("/templates/{template_id}", response_model=LoopTemplateResponse)
def get_template_endpoint(template_id: int, settings: SettingsDep) -> LoopTemplateResponse:
    """Get a single template by ID."""
    with db.core_connection(settings) as conn:
        template = get_loop_template(template_id=template_id, conn=conn)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return _template_to_response(template)


@router.post("/templates", response_model=LoopTemplateResponse, status_code=201)
def create_template_endpoint(
    request: LoopTemplateCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopTemplateResponse | JSONResponse:
    """Create a new loop template."""
    with db.core_connection(settings) as conn:
        try:
            template = create_loop_template(
                name=request.name,
                description=request.description,
                raw_text_pattern=request.raw_text_pattern,
                defaults_json=request.defaults,
                is_system=False,
                conn=conn,
            )
        except ValidationError as e:
            raise HTTPException(status_code=400, detail={"message": e.message}) from None

    return _template_to_response(template)


@router.patch("/templates/{template_id}", response_model=LoopTemplateResponse)
def update_template_endpoint(
    template_id: int,
    request: LoopTemplateUpdateRequest,
    settings: SettingsDep,
) -> LoopTemplateResponse:
    """Update a loop template. System templates cannot be modified."""
    with db.core_connection(settings) as conn:
        try:
            template = update_loop_template(
                template_id=template_id,
                name=request.name,
                description=request.description,
                raw_text_pattern=request.raw_text_pattern,
                defaults_json=request.defaults,
                conn=conn,
            )
        except ValidationError as e:
            raise HTTPException(status_code=400, detail={"message": e.message}) from None

    return _template_to_response(template)


@router.delete("/templates/{template_id}")
def delete_template_endpoint(template_id: int, settings: SettingsDep) -> dict[str, bool]:
    """Delete a loop template. System templates cannot be deleted."""
    with db.core_connection(settings) as conn:
        try:
            deleted = delete_loop_template(template_id=template_id, conn=conn)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail={"message": e.message}) from None

    return {"deleted": deleted}


@router.post("/{loop_id}/save-as-template", response_model=LoopTemplateResponse, status_code=201)
def save_as_template_endpoint(
    loop_id: int,
    request: LoopTemplateCreateRequest,
    settings: SettingsDep,
) -> LoopTemplateResponse:
    """Create a template from an existing loop."""
    with db.core_connection(settings) as conn:
        try:
            template = create_template_from_loop(
                loop_id=loop_id,
                template_name=request.name,
                conn=conn,
            )
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None
        except ValidationError as e:
            raise HTTPException(status_code=400, detail={"message": e.message}) from None

    return _template_to_response(template)
