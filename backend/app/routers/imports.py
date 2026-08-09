from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.schemas.common import ApiResponse, ok_response
from app.schemas.imports import ImportResumeResponse, ImportTemplatesResponse
from app.services.imports import (
    load_json_upload,
    parse_resume_artifact,
    parse_template_artifact,
)

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/resume", response_model=ApiResponse[ImportResumeResponse])
async def import_resume(
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportResumeResponse]:
    """Import resume items from an uploaded JSON file."""

    payload = await load_json_upload(file)
    artifact = parse_resume_artifact(payload)

    return ok_response(
        ImportResumeResponse(
            templates=artifact.templates,
            resumes=artifact.resumes,
        )
    )


@router.post("/templates", response_model=ApiResponse[ImportTemplatesResponse])
async def import_templates(
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportTemplatesResponse]:
    """Import resume templates from an uploaded JSON file."""

    payload = await load_json_upload(file)
    templates = parse_template_artifact(payload)

    return ok_response(ImportTemplatesResponse(templates=templates))
