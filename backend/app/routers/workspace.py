from typing import Any

from fastapi import APIRouter, Query

from app.schemas.common import ApiResponse, ok_response
from app.schemas.workspace import (
    DefaultTemplateSaveRequest,
    UserSettingsSaveRequest,
)
from app.services.workspace import (
    load_workspace,
    save_default_template,
    save_user_settings,
)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/bootstrap", response_model=ApiResponse[dict[str, Any]])
def get_workspace_bootstrap(
    locale: str = Query(default="zh"),
) -> ApiResponse[dict[str, Any]]:
    """Return the current workspace bootstrap payload."""

    return ok_response(load_workspace(locale))


@router.put("/user-settings", response_model=ApiResponse[dict[str, Any]])
def put_user_settings(
    request: UserSettingsSaveRequest,
    locale: str = Query(default="zh"),
) -> ApiResponse[dict[str, Any]]:
    """Persist settings-page preferences without saving resume content."""

    return ok_response(save_user_settings(locale, request.settings))


@router.put("/default-template", response_model=ApiResponse[dict[str, Any]])
def put_default_template(
    request: DefaultTemplateSaveRequest,
) -> ApiResponse[dict[str, Any]]:
    """Persist the workspace default template."""

    return ok_response(save_default_template(request.template_id))
