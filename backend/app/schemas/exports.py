from pydantic import BaseModel, ConfigDict, Field

from app.agent_locales import AgentLocale


class ExportResumeRenderRequest(BaseModel):
    """Shared request fields for exports rendered by the frontend preview."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resume_id: str = Field(alias="resumeId")
    locale: AgentLocale
    file_name_seed: str = Field(alias="fileNameSeed")
    saved_at: str = Field(alias="savedAt")
    version_id: str | None = Field(default=None, alias="versionId")


class ExportResumePdfRequest(ExportResumeRenderRequest):
    """Request body for exporting a saved resume as PDF."""


class ExportResumeImagesRequest(ExportResumeRenderRequest):
    """Request body for exporting each saved resume page as a PNG image."""


class ExportResumePdfResponse(BaseModel):
    """PDF export metadata returned to the frontend."""

    export_id: str = Field(alias="exportId")
    download_url: str = Field(alias="downloadUrl")
    file_name: str = Field(alias="fileName")
    expires_at: str = Field(alias="expiresAt")


class ExportResumeImagesResponse(ExportResumePdfResponse):
    """Image export metadata returned to the frontend."""

    page_count: int = Field(alias="pageCount")
    is_archive: bool = Field(alias="isArchive")
