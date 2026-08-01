from typing import Literal

from fastapi import APIRouter, Query

from app.schemas.common import ApiResponse, ok_response
from app.schemas.workspace import (
    DefaultTemplateSaveRequest,
    DefaultTemplateSaveResponse,
    ModelsPageResponse,
    ResumeEditorPageResponse,
    ResumesPageResponse,
    SettingsPageResponse,
    TemplatesPageResponse,
    TrashPageResponse,
    UserSettingsSaveRequest,
    UserSettingsSaveResponse,
)
from app.services.templates import save_default_template
from app.services.user_preferences import save_user_settings
from app.services.workspace_pages import (
    load_models_page,
    load_resume_editor_page,
    load_resumes_page,
    load_settings_page,
    load_templates_page,
    load_trash_page,
)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get(
    "/pages/resumes",
    response_model=ApiResponse[ResumesPageResponse],
    response_model_exclude_none=True,
)
def get_resumes_page() -> ApiResponse[ResumesPageResponse]:
    return ok_response(load_resumes_page())


@router.get(
    "/pages/resume-editor",
    response_model=ApiResponse[ResumeEditorPageResponse],
    response_model_exclude_none=True,
)
def get_resume_editor_page() -> ApiResponse[ResumeEditorPageResponse]:
    return ok_response(load_resume_editor_page())


@router.get(
    "/pages/templates",
    response_model=ApiResponse[TemplatesPageResponse],
    response_model_exclude_none=True,
)
def get_templates_page() -> ApiResponse[TemplatesPageResponse]:
    return ok_response(load_templates_page())


@router.get(
    "/pages/trash",
    response_model=ApiResponse[TrashPageResponse],
    response_model_exclude_none=True,
)
def get_trash_page() -> ApiResponse[TrashPageResponse]:
    return ok_response(load_trash_page())


@router.get(
    "/pages/models",
    response_model=ApiResponse[ModelsPageResponse],
    response_model_exclude_none=True,
)
def get_models_page() -> ApiResponse[ModelsPageResponse]:
    return ok_response(load_models_page())


@router.get(
    "/pages/settings",
    response_model=ApiResponse[SettingsPageResponse],
    response_model_exclude_none=True,
)
def get_settings_page() -> ApiResponse[SettingsPageResponse]:
    return ok_response(load_settings_page())


@router.put(
    "/user-settings",
    response_model=ApiResponse[UserSettingsSaveResponse],
    response_model_exclude_none=True,
)
def put_user_settings(
    request: UserSettingsSaveRequest,
    locale: Literal["zh", "en"] = Query(default="zh"),
) -> ApiResponse[UserSettingsSaveResponse]:
    """Persist settings-page preferences without saving resume content."""

    settings = request.settings.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
        exclude_unset=True,
    )
    return ok_response(
        UserSettingsSaveResponse.model_validate(save_user_settings(locale, settings))
    )


@router.put(
    "/default-template",
    response_model=ApiResponse[DefaultTemplateSaveResponse],
)
def put_default_template(
    request: DefaultTemplateSaveRequest,
) -> ApiResponse[DefaultTemplateSaveResponse]:
    """Persist the workspace default template."""

    return ok_response(
        DefaultTemplateSaveResponse.model_validate(
            save_default_template(request.template_id)
        )
    )
