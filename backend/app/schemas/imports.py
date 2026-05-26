from typing import Any

from pydantic import BaseModel


class ImportResumeResponse(BaseModel):
    """Resume items extracted from an uploaded JSON file."""

    resumes: list[dict[str, Any]]


class ImportTemplatesResponse(BaseModel):
    """Template items extracted from an uploaded JSON file."""

    templates: list[dict[str, Any]]
