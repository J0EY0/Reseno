from pydantic import BaseModel, ConfigDict, Field

from app.schemas.imports import TemplateArtifactItem


class TemplateDefinitionResponse(TemplateArtifactItem):
    """Stable top-level shape of a custom resume template."""

    id: str
    updated_at: str = Field(alias="updatedAt")
    is_built_in: bool = Field(alias="isBuiltIn")


class DeletedTemplateDefinitionResponse(TemplateDefinitionResponse):
    """Recycle-bin template with deletion metadata."""

    deleted_at: str = Field(alias="deletedAt")


class TemplateSaveRequest(BaseModel):
    """Custom template payload saved through template commands."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template: TemplateArtifactItem


class TemplateResponse(BaseModel):
    """Response body for one custom template."""

    template: TemplateDefinitionResponse | DeletedTemplateDefinitionResponse


class TemplateListResponse(BaseModel):
    """Collection response for custom templates."""

    templates: list[TemplateDefinitionResponse | DeletedTemplateDefinitionResponse]


class TemplateDeleteResponse(BaseModel):
    """Response body for a permanent single template delete."""

    id: str


class TemplateTrashEmptyResponse(BaseModel):
    """Response body for emptying the template recycle bin."""

    deleted_count: int = Field(alias="deletedCount")
