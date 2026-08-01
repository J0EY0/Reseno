from typing import Any

from pydantic import BaseModel, ConfigDict, Field

JsonObject = dict[str, Any]


class TemplateDefinitionResponse(BaseModel):
    """Stable top-level shape of a custom resume template."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    preset: str
    name: str
    description: str
    layout: JsonObject
    typography: JsonObject
    settings: JsonObject
    updated_at: str = Field(alias="updatedAt")
    is_built_in: bool | None = Field(default=None, alias="isBuiltIn")


class DeletedTemplateDefinitionResponse(TemplateDefinitionResponse):
    """Recycle-bin template with deletion metadata."""

    deleted_at: str = Field(alias="deletedAt")


class TemplateSaveRequest(BaseModel):
    """Custom template payload saved through template commands."""

    template: JsonObject


class TemplateResponse(BaseModel):
    """Response body for one custom template."""

    template: JsonObject


class TemplateListResponse(BaseModel):
    """Collection response for custom templates."""

    templates: list[JsonObject]


class TemplateDeleteResponse(BaseModel):
    """Response body for a permanent single template delete."""

    id: str


class TemplateTrashEmptyResponse(BaseModel):
    """Response body for emptying the template recycle bin."""

    deleted_count: int = Field(alias="deletedCount")
