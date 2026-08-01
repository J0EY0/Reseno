from typing import Literal

from fastapi import APIRouter, Query

from app.schemas.common import ApiResponse, ok_response
from app.schemas.templates import (
    TemplateDeleteResponse,
    TemplateListResponse,
    TemplateResponse,
    TemplateSaveRequest,
    TemplateTrashEmptyResponse,
)
from app.services.templates import (
    create_template,
    delete_template_forever,
    empty_template_trash,
    list_templates,
    restore_template,
    trash_template,
    update_template,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=ApiResponse[TemplateListResponse])
def get_templates(
    status_filter: Literal["active", "deleted"] = Query(
        default="active",
        alias="status",
    ),
) -> ApiResponse[TemplateListResponse]:
    """Return active or deleted custom templates."""

    return ok_response(
        TemplateListResponse.model_validate(list_templates(status_filter))
    )


@router.post("", response_model=ApiResponse[TemplateResponse])
def post_template(request: TemplateSaveRequest) -> ApiResponse[TemplateResponse]:
    """Create a backend-owned custom template."""

    return ok_response(
        TemplateResponse.model_validate(create_template(request.template))
    )


@router.delete("/trash", response_model=ApiResponse[TemplateTrashEmptyResponse])
def delete_template_trash() -> ApiResponse[TemplateTrashEmptyResponse]:
    """Physically delete every custom template in the recycle bin."""

    return ok_response(
        TemplateTrashEmptyResponse.model_validate(empty_template_trash())
    )


@router.put("/{template_id}", response_model=ApiResponse[TemplateResponse])
def put_template(
    template_id: str,
    request: TemplateSaveRequest,
) -> ApiResponse[TemplateResponse]:
    """Replace one active custom template."""

    return ok_response(
        TemplateResponse.model_validate(update_template(template_id, request.template))
    )


@router.post("/{template_id}/trash", response_model=ApiResponse[TemplateResponse])
def post_template_trash(template_id: str) -> ApiResponse[TemplateResponse]:
    """Move one custom template into the recycle bin."""

    return ok_response(TemplateResponse.model_validate(trash_template(template_id)))


@router.post("/{template_id}/restore", response_model=ApiResponse[TemplateResponse])
def post_template_restore(template_id: str) -> ApiResponse[TemplateResponse]:
    """Restore one deleted custom template."""

    return ok_response(TemplateResponse.model_validate(restore_template(template_id)))


@router.delete("/{template_id}", response_model=ApiResponse[TemplateDeleteResponse])
def delete_template(template_id: str) -> ApiResponse[TemplateDeleteResponse]:
    """Physically delete one already-deleted custom template."""

    return ok_response(
        TemplateDeleteResponse.model_validate(delete_template_forever(template_id))
    )
