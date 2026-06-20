from typing import Any

from pydantic import BaseModel, Field

JsonObject = dict[str, Any]


class ResumeCreateRequest(BaseModel):
    """Optional overrides for a backend-created resume."""

    title: str | None = None
    resume: JsonObject | None = None
    job_brief: str | None = Field(default=None, alias="jobBrief")
    typography: JsonObject | None = None
    template: str | None = None
    template_settings: JsonObject | None = Field(default=None, alias="templateSettings")


class ResumeSaveRequest(BaseModel):
    """Full resume payload persisted by PUT /api/resumes/{id}."""

    title: str | None = None
    resume: JsonObject | None = None
    job_brief: str | None = Field(default=None, alias="jobBrief")
    typography: JsonObject | None = None
    template: str | None = None
    template_settings: JsonObject | None = Field(default=None, alias="templateSettings")


class ResumeDetailResponse(BaseModel):
    """Saved resume item plus version metadata."""

    resume: JsonObject
    saved_at: str = Field(alias="savedAt")
    version_id: str = Field(alias="versionId")


class ResumeListResponse(BaseModel):
    """Collection response for active or deleted resumes."""

    resumes: list[JsonObject]


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
