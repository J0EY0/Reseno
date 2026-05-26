from typing import Literal

from pydantic import BaseModel, Field


class ExportResumePdfRequest(BaseModel):
    """Request body for exporting a saved resume as PDF."""

    resume_id: str = Field(alias="resumeId")
    locale: Literal["zh", "en"]
    file_name_seed: str = Field(alias="fileNameSeed")
    saved_at: str = Field(alias="savedAt")
    version_id: str | None = Field(default=None, alias="versionId")
    render_base_url: str | None = Field(default=None, alias="renderBaseUrl")


class ExportResumePdfResponse(BaseModel):
    """PDF export metadata returned to the frontend."""

    export_id: str = Field(alias="exportId")
    download_url: str = Field(alias="downloadUrl")
    file_name: str = Field(alias="fileName")
    expires_at: str | None = Field(default=None, alias="expiresAt")
