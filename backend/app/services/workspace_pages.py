from sqlite3 import Connection
from typing import Any

from app.db.connection import connect
from app.schemas.agent_settings import AgentSettings, normalize_agent_settings
from app.schemas.model_configs import ModelConfigResponse
from app.schemas.resumes import (
    DeletedResumeWorkspaceItemResponse,
    ResumeWorkspaceItemResponse,
)
from app.schemas.templates import (
    DeletedTemplateDefinitionResponse,
    TemplateDefinitionResponse,
)
from app.schemas.workspace import (
    ModelsPageResponse,
    ResumeEditorPageResponse,
    ResumesPageResponse,
    SettingsPageResponse,
    TemplatesPageResponse,
    ThemeMode,
    TrashPageResponse,
)
from app.services.model_configs import list_llm_configs
from app.services.user_preferences import load_user_settings, normalize_theme
from app.services.workspace import (
    _load_resume_items,
    _load_template_items,
    _load_workspace_state,
    workspace_data_locale,
)


def _template_context(
    conn: Connection,
) -> tuple[str, list[TemplateDefinitionResponse]]:
    """Load the active template catalog and its default selection."""

    state = _load_workspace_state(conn)
    templates = [
        TemplateDefinitionResponse.model_validate(item)
        for item in _load_template_items(
            conn,
            locale=workspace_data_locale(),
            deleted=False,
        )
    ]
    return state["defaultTemplateId"], templates


def _model_context(
    conn: Connection,
    settings: dict[str, Any],
) -> tuple[list[ModelConfigResponse], AgentSettings]:
    """Load model configs and normalize settings that reference them."""

    return (
        list_llm_configs(conn),
        normalize_agent_settings(settings.get("agentSettings")),
    )


def load_resumes_page() -> ResumesPageResponse:
    """Load the exact initialization contract for the resume gallery."""

    settings = load_user_settings()
    with connect() as conn:
        default_template_id, custom_templates = _template_context(conn)
        resumes = [
            ResumeWorkspaceItemResponse.model_validate(item)
            for item in _load_resume_items(
                conn,
                locale=workspace_data_locale(),
                deleted=False,
            )
        ]

    return ResumesPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateId=default_template_id,
        customTemplates=custom_templates,
        resumes=resumes,
    )


def load_resume_editor_page() -> ResumeEditorPageResponse:
    """Load shared dependencies required by a resume editor page."""

    settings = load_user_settings()
    with connect() as conn:
        default_template_id, custom_templates = _template_context(conn)
        model_configs, agent_settings = _model_context(conn, settings)

    return ResumeEditorPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateId=default_template_id,
        customTemplates=custom_templates,
        modelConfigs=model_configs,
        agentSettings=agent_settings,
    )


def load_templates_page() -> TemplatesPageResponse:
    """Load the template catalog used by template pages and PDF export."""

    settings = load_user_settings()
    with connect() as conn:
        default_template_id, custom_templates = _template_context(conn)

    return TemplatesPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateId=default_template_id,
        customTemplates=custom_templates,
    )


def load_trash_page() -> TrashPageResponse:
    """Load deleted items and the active templates used to preview them."""

    settings = load_user_settings()
    with connect() as conn:
        default_template_id, custom_templates = _template_context(conn)
        deleted_resumes = [
            DeletedResumeWorkspaceItemResponse.model_validate(item)
            for item in _load_resume_items(
                conn,
                locale=workspace_data_locale(),
                deleted=True,
            )
        ]
        deleted_templates = [
            DeletedTemplateDefinitionResponse.model_validate(item)
            for item in _load_template_items(
                conn,
                locale=workspace_data_locale(),
                deleted=True,
            )
        ]

    return TrashPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateId=default_template_id,
        customTemplates=custom_templates,
        deletedResumes=deleted_resumes,
        deletedTemplates=deleted_templates,
    )


def _load_model_settings_context() -> tuple[
    ThemeMode | None,
    list[ModelConfigResponse],
    AgentSettings,
]:
    """Load data shared by the model and settings page contracts."""
    settings = load_user_settings()
    with connect() as conn:
        model_configs, agent_settings = _model_context(conn, settings)

    return normalize_theme(settings.get("theme")), model_configs, agent_settings


def load_models_page() -> ModelsPageResponse:
    """Load the exact initialization contract for the model configuration page."""

    theme, model_configs, agent_settings = _load_model_settings_context()
    return ModelsPageResponse(
        theme=theme,
        modelConfigs=model_configs,
        agentSettings=agent_settings,
    )


def load_settings_page() -> SettingsPageResponse:
    """Load the exact initialization contract for the user settings page."""

    theme, model_configs, agent_settings = _load_model_settings_context()
    return SettingsPageResponse(
        theme=theme,
        modelConfigs=model_configs,
        agentSettings=agent_settings,
    )
