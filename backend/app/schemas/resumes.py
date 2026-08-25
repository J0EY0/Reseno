import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.imports import TemplateSettingsOverrides, TypographySettings

JsonObject = dict[str, Any]
MAX_RESUME_TITLE_LENGTH = 50
RESUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,160}$")


def is_valid_resume_id(value: str) -> bool:
    """Return whether a workspace resume id uses the canonical alphabet."""

    return bool(RESUME_ID_PATTERN.fullmatch(value))


class ResumeWorkspaceItemResponse(BaseModel):
    """Stable top-level shape of a resume returned to workspace clients."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    title: str
    updated_at: str = Field(alias="updatedAt")
    resume: JsonObject
    job_brief: str = Field(alias="jobBrief")
    typography: TypographySettings
    template: str = Field(min_length=1)
    template_settings: TemplateSettingsOverrides | None = Field(
        alias="templateSettings",
    )


class DeletedResumeWorkspaceItemResponse(ResumeWorkspaceItemResponse):
    """Recycle-bin resume preview with deletion metadata."""

    deleted_at: str = Field(alias="deletedAt")


class ResumeCreateRequest(BaseModel):
    """Optional overrides for a backend-created resume."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None = Field(default=None, max_length=MAX_RESUME_TITLE_LENGTH)
    resume: JsonObject | None = None
    job_brief: str | None = Field(default=None, alias="jobBrief")
    typography: TypographySettings | None = None
    template: str | None = Field(default=None, min_length=1)
    template_settings: TemplateSettingsOverrides | None = Field(
        default=None,
        alias="templateSettings",
    )


class ResumeSaveRequest(BaseModel):
    """Full resume payload persisted by PUT /api/resumes/{id}."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(max_length=MAX_RESUME_TITLE_LENGTH)
    resume: JsonObject
    job_brief: str = Field(alias="jobBrief")
    typography: TypographySettings
    template: str = Field(min_length=1)
    template_settings: TemplateSettingsOverrides | None = Field(
        alias="templateSettings",
    )


class ResumeDetailResponse(BaseModel):
    """Saved resume item plus version metadata."""

    resume: ResumeWorkspaceItemResponse
    saved_at: str = Field(alias="savedAt")
    version_id: str = Field(alias="versionId")


class ResumeListResponse(BaseModel):
    """Collection response for active or deleted resumes."""

    resumes: list[ResumeWorkspaceItemResponse | DeletedResumeWorkspaceItemResponse]


class ResumeDeleteResponse(BaseModel):
    """Response body for a permanent single resume delete."""

    id: str


class ResumeTrashEmptyResponse(BaseModel):
    """Response body for emptying the resume recycle bin."""

    deleted_count: int = Field(alias="deletedCount")


class ResumeVersionSummary(BaseModel):
    """Summary row for one resume version."""

    version_id: str = Field(alias="versionId")
    saved_at: str = Field(alias="savedAt")


class ResumeVersionsResponse(BaseModel):
    """Collection response for resume versions."""

    versions: list[ResumeVersionSummary]
