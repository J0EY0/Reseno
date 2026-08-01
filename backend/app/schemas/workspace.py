from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_settings import AgentSettings
from app.schemas.model_configs import ModelConfigResponse
from app.schemas.resumes import (
    DeletedResumeWorkspaceItemResponse,
    ResumeWorkspaceItemResponse,
)
from app.schemas.templates import (
    DeletedTemplateDefinitionResponse,
    TemplateDefinitionResponse,
)

ThemeMode = Literal["light", "dark", "system"]


class UserSettingsUpdate(BaseModel):
    """Supported user preferences accepted by the settings command."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    theme: ThemeMode | None = None
    agent_settings: AgentSettings | None = Field(default=None, alias="agentSettings")


class UserSettingsSaveRequest(BaseModel):
    """Request body containing settings-page preferences."""

    settings: UserSettingsUpdate


class UserSettingsSaveResponse(BaseModel):
    """Normalized user preferences after a successful update."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    locale: Literal["zh", "en"]
    theme: ThemeMode | None = None
    agent_settings: AgentSettings | None = Field(default=None, alias="agentSettings")


class DefaultTemplateSaveRequest(BaseModel):
    """Request body for setting the workspace default template."""

    template_id: str = Field(alias="templateId")


class DefaultTemplateSaveResponse(BaseModel):
    """Current default template after a successful update."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    default_template_id: str = Field(alias="defaultTemplateId")


class WorkspacePageResponse(BaseModel):
    """Preferences shared by authenticated workspace page responses."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    theme: ThemeMode | None = None


class TemplateContextPageResponse(WorkspacePageResponse):
    """Template catalog fields shared by template-aware pages."""

    default_template_id: str = Field(alias="defaultTemplateId")
    custom_templates: list[TemplateDefinitionResponse] = Field(alias="customTemplates")


class ModelSettingsPageResponse(WorkspacePageResponse):
    """Model and Agent settings shared by model-aware pages."""

    model_configs: list[ModelConfigResponse] = Field(alias="modelConfigs")
    agent_settings: AgentSettings = Field(alias="agentSettings")


class ResumesPageResponse(TemplateContextPageResponse):
    """Exact initialization contract for the resume gallery page."""

    resumes: list[ResumeWorkspaceItemResponse]


class ResumeEditorPageResponse(
    TemplateContextPageResponse,
    ModelSettingsPageResponse,
):
    """Exact shared-dependency contract for a resume editor page."""


class TemplatesPageResponse(TemplateContextPageResponse):
    """Exact template catalog contract used by template pages and PDF export."""


class TrashPageResponse(TemplateContextPageResponse):
    """Exact recycle-bin contract with limited deleted-item previews."""

    deleted_resumes: list[DeletedResumeWorkspaceItemResponse] = Field(
        alias="deletedResumes"
    )
    deleted_templates: list[DeletedTemplateDefinitionResponse] = Field(
        alias="deletedTemplates"
    )


class ModelsPageResponse(ModelSettingsPageResponse):
    """Exact initialization contract for the model configuration page."""


class SettingsPageResponse(ModelSettingsPageResponse):
    """Exact initialization contract for the user settings page."""
