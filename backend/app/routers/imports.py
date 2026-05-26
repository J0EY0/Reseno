from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.schemas.common import ApiResponse, ok_response
from app.schemas.imports import ImportResumeResponse, ImportTemplatesResponse
from app.services.imports import (
    coerce_resume_import,
    coerce_template_import,
    load_json_upload,
)

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/resume", response_model=ApiResponse[ImportResumeResponse])
async def import_resume(
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportResumeResponse]:
    """Import resume items from an uploaded JSON file."""

    payload = await load_json_upload(file)
    resumes = coerce_resume_import(payload)

    if not resumes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No resume data found in the uploaded JSON.",
        )

    return ok_response(ImportResumeResponse(resumes=resumes))


@router.post("/templates", response_model=ApiResponse[ImportTemplatesResponse])
async def import_templates(
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportTemplatesResponse]:
    """Import resume templates from an uploaded JSON file."""

    payload = await load_json_upload(file)
    templates = coerce_template_import(payload)

    if not templates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No template data found in the uploaded JSON.",
        )

    return ok_response(ImportTemplatesResponse(templates=templates))
