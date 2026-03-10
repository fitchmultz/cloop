"""Loop template endpoints.

Purpose:
    HTTP endpoints for managing loop templates.

Responsibilities:
    - Create, read, update, and delete loop templates
    - Convert existing loops into templates
    - Provide template listing and retrieval

Non-scope:
    - Loop CRUD operations (see core.py)
    - Template auto-application or matching logic
    - Template versioning or inheritance

Endpoints:
- GET /templates: List all templates
- GET /templates/{template_id}: Get a single template
- POST /templates: Create a new template
- PATCH /templates/{template_id}: Update a template
- DELETE /templates/{template_id}: Delete a template
- POST /{loop_id}/save-as-template: Create template from an existing loop
"""

from fastapi import APIRouter
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
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    build_loop_template_response,
    map_not_found_to_404,
    map_validation_to_400,
    no_fields_to_update_http_exception,
    run_idempotent_loop_route,
)

router = APIRouter()


@router.get("/templates", response_model=LoopTemplateListResponse)
def list_templates_endpoint(settings: SettingsDep) -> LoopTemplateListResponse:
    """List all loop templates."""
    with db.core_connection(settings) as conn:
        templates = list_loop_templates(conn=conn)

    return LoopTemplateListResponse(
        templates=[build_loop_template_response(template) for template in templates]
    )


@router.get("/templates/{template_id}", response_model=LoopTemplateResponse)
def get_template_endpoint(template_id: int, settings: SettingsDep) -> LoopTemplateResponse:
    """Get a single template by ID."""
    with db.core_connection(settings) as conn:
        template = get_loop_template(template_id=template_id, conn=conn)

    if not template:
        raise map_not_found_to_404(resource_type="template") from None

    return build_loop_template_response(template)


@router.post("/templates", response_model=LoopTemplateResponse, status_code=201)
def create_template_endpoint(
    request: LoopTemplateCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopTemplateResponse | JSONResponse:
    """Create a new loop template."""
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path="/loops/templates",
            idempotency_key=idempotency_key,
            payload=request.model_dump(),
            response_status=201,
            execute=lambda conn: build_loop_template_response(
                create_loop_template(
                    name=request.name,
                    description=request.description,
                    raw_text_pattern=request.raw_text_pattern,
                    defaults_json=request.defaults,
                    is_system=False,
                    conn=conn,
                )
            ).model_dump(),
        )
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None

    if isinstance(result, JSONResponse):
        return result
    return LoopTemplateResponse(**result)


@router.patch("/templates/{template_id}", response_model=LoopTemplateResponse)
def update_template_endpoint(
    template_id: int,
    request: LoopTemplateUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopTemplateResponse | JSONResponse:
    """Update a loop template. System templates cannot be modified."""
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise no_fields_to_update_http_exception() from None

    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="PATCH",
            path=f"/loops/templates/{template_id}",
            idempotency_key=idempotency_key,
            payload={"template_id": template_id, "fields": fields},
            execute=lambda conn: build_loop_template_response(
                update_loop_template(
                    template_id=template_id,
                    name=fields.get("name"),
                    description=fields.get("description"),
                    raw_text_pattern=fields.get("raw_text_pattern"),
                    defaults_json=fields.get("defaults"),
                    conn=conn,
                )
            ).model_dump(),
        )
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None

    if isinstance(result, JSONResponse):
        return result
    return LoopTemplateResponse(**result)


@router.delete("/templates/{template_id}", response_model=None)
def delete_template_endpoint(
    template_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> dict[str, bool] | JSONResponse:
    """Delete a loop template. System templates cannot be deleted."""
    try:
        return run_idempotent_loop_route(
            settings=settings,
            method="DELETE",
            path=f"/loops/templates/{template_id}",
            idempotency_key=idempotency_key,
            payload={"template_id": template_id},
            execute=lambda conn: {
                "deleted": delete_loop_template(template_id=template_id, conn=conn)
            },
        )
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None


@router.post("/{loop_id}/save-as-template", response_model=LoopTemplateResponse, status_code=201)
def save_as_template_endpoint(
    loop_id: int,
    request: LoopTemplateCreateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopTemplateResponse | JSONResponse:
    """Create a template from an existing loop."""
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path=f"/loops/{loop_id}/save-as-template",
            idempotency_key=idempotency_key,
            payload={"loop_id": loop_id, **request.model_dump()},
            response_status=201,
            execute=lambda conn: build_loop_template_response(
                create_template_from_loop(
                    loop_id=loop_id,
                    template_name=request.name,
                    conn=conn,
                )
            ).model_dump(),
        )
    except LoopNotFoundError:
        raise map_not_found_to_404(resource_type="loop") from None
    except ValidationError as exc:
        raise map_validation_to_400(exc) from None

    if isinstance(result, JSONResponse):
        return result
    return LoopTemplateResponse(**result)
