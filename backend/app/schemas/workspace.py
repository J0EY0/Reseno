from typing import Any

from pydantic import BaseModel, Field

JsonObject = dict[str, Any]


class WorkspaceSaveRequest(BaseModel):
    """Request body containing a full frontend workspace snapshot."""

    snapshot: JsonObject


class WorkspaceSaveResponse(BaseModel):
    """Save metadata returned after persisting a workspace snapshot."""

    saved_at: str = Field(alias="savedAt")
    version_id: str = Field(alias="versionId")


class WorkspaceVersionSummary(BaseModel):
    """Summary row for one available workspace version."""

    version_id: str = Field(alias="versionId")
    saved_at: str = Field(alias="savedAt")


class WorkspaceVersionsResponse(BaseModel):
    """Collection response for workspace version summaries."""

    versions: list[WorkspaceVersionSummary]


class WorkspaceVersionResponse(BaseModel):
    """Response body for a reconstructed workspace version."""

    version_id: str = Field(alias="versionId")
    snapshot: JsonObject
