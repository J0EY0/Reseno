from typing import Any

from app.schemas.agent_settings import AgentSettings, normalize_agent_settings
from app.schemas.model_configs import ModelConfigResponse
from app.schemas.resumes import DeletedResumeWorkspaceItemResponse
from app.schemas.templates import (
    DeletedTemplateDefinitionResponse,
    TemplateDefinitionResponse,
)
from app.schemas.workspace import (
    DefaultTemplateIds,
    ModelsPageResponse,
    ResumeEditorPageResponse,
    ResumesPageResponse,
    SettingsPageResponse,
    TemplatesPageResponse,
    ThemeMode,
    TrashPageResponse,
)
from app.services.model_configs import list_llm_configs
from app.services.resumes import list_resumes
from app.services.templates import list_templates, load_template_catalog
from app.services.user_preferences import load_user_settings, normalize_theme


def _template_context() -> tuple[
    DefaultTemplateIds,
    list[TemplateDefinitionResponse],
]:
    """Load the active template catalog and its default selection."""

    catalog = load_template_catalog()
    templates = [
        TemplateDefinitionResponse.model_validate(item) for item in catalog.templates
    ]
    return DefaultTemplateIds.model_validate(catalog.default_template_ids), templates


def _model_context(
    settings: dict[str, Any],
) -> tuple[list[ModelConfigResponse], AgentSettings]:
    """Load model configs and normalize settings that reference them."""

    return (
        list_llm_configs(),
        normalize_agent_settings(settings.get("agentSettings")),
    )


def load_resumes_page() -> ResumesPageResponse:
    """Load the exact initialization contract for the resume gallery."""

    settings = load_user_settings()
    default_template_ids, custom_templates = _template_context()
    resumes = list_resumes("active").resumes

    return ResumesPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateIds=default_template_ids,
        customTemplates=custom_templates,
        resumes=resumes,
    )


def load_resume_editor_page() -> ResumeEditorPageResponse:
    """Load shared dependencies required by a resume editor page."""

    settings = load_user_settings()
    default_template_ids, custom_templates = _template_context()
    model_configs, agent_settings = _model_context(settings)

    return ResumeEditorPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateIds=default_template_ids,
        customTemplates=custom_templates,
        modelConfigs=model_configs,
        agentSettings=agent_settings,
    )


def load_templates_page() -> TemplatesPageResponse:
    """Load the template catalog used by template pages and PDF export."""

    settings = load_user_settings()
    default_template_ids, custom_templates = _template_context()

    return TemplatesPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateIds=default_template_ids,
        customTemplates=custom_templates,
    )


def load_trash_page() -> TrashPageResponse:
    """Load deleted items and the active templates used to preview them."""

    settings = load_user_settings()
    default_template_ids, custom_templates = _template_context()
    deleted_resumes = [
        DeletedResumeWorkspaceItemResponse.model_validate(item)
        for item in list_resumes("deleted").resumes
    ]
    deleted_templates = [
        DeletedTemplateDefinitionResponse.model_validate(item)
        for item in list_templates("deleted")["templates"]
    ]

    return TrashPageResponse(
        theme=normalize_theme(settings.get("theme")),
        defaultTemplateIds=default_template_ids,
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
    model_configs, agent_settings = _model_context(settings)

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
