from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from starlette.concurrency import run_in_threadpool

from app.routers.upload_route import LimitedUploadRoute
from app.schemas.common import ApiResponse, ok_response
from app.schemas.imports import ImportResumeResponse, ImportTemplatesResponse
from app.services.imports import (
    load_json_upload,
    parse_resume_artifact,
    parse_template_artifact,
)

router = APIRouter(
    prefix="/api/import", tags=["import"], route_class=LimitedUploadRoute
)


@router.post("/resume", response_model=ApiResponse[ImportResumeResponse])
async def import_resume(
    file: Annotated[UploadFile, File()],
) -> ApiResponse[ImportResumeResponse]:
    """Import resume items from an uploaded JSON file."""

    payload = await load_json_upload(file)
    artifact = await run_in_threadpool(parse_resume_artifact, payload)

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
    templates = await run_in_threadpool(parse_template_artifact, payload)

    return ok_response(ImportTemplatesResponse(templates=templates))
