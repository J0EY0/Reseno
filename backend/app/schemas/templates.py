from typing import Any

from pydantic import BaseModel, Field

JsonObject = dict[str, Any]


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
