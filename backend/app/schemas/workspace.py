from typing import Any

from pydantic import BaseModel, Field

JsonObject = dict[str, Any]


class UserSettingsSaveRequest(BaseModel):
    """Request body containing settings-page preferences."""

    settings: JsonObject


class DefaultTemplateSaveRequest(BaseModel):
    """Request body for setting the workspace default template."""

    template_id: str = Field(alias="templateId")
