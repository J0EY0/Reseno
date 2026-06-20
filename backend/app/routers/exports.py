from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.schemas.common import ApiResponse, ok_response
from app.schemas.exports import ExportResumePdfRequest, ExportResumePdfResponse
from app.services.auth_tokens import format_token_expiry
from app.services.pdf import (
    create_export_id,
    require_export_file,
    safe_file_name,
    write_resume_pdf,
)
from app.services.workspace import load_resume, load_resume_version

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("/resume-pdf", response_model=ApiResponse[ExportResumePdfResponse])
def export_resume_pdf(
    request: ExportResumePdfRequest,
    http_request: Request,
) -> ApiResponse[ExportResumePdfResponse]:
    """Generate a PDF export for a saved resume."""

    try:
        if request.version_id:
            load_resume_version(request.resume_id, request.version_id)
        else:
            load_resume(request.resume_id)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found for PDF export.",
        ) from exc

    export_id = create_export_id()
    file_name = safe_file_name(request.file_name_seed)
    auth_payload = getattr(http_request.state, "auth_payload", None)
    access_token = getattr(http_request.state, "auth_token", None)
    write_resume_pdf(
        export_id,
        request,
        access_token=access_token,
        token_expires_at=(
            format_token_expiry(auth_payload.expires_at) if auth_payload else None
        ),
        username=auth_payload.subject if auth_payload else None,
    )
    download_query = urlencode({"fileName": file_name})

    return ok_response(
        ExportResumePdfResponse(
            exportId=export_id,
            downloadUrl=f"/api/exports/download/{export_id}?{download_query}",
            fileName=file_name,
            expiresAt=None,
        ),
    )


@router.get("/download/{export_id}")
def download_export(export_id: str, fileName: str | None = None) -> FileResponse:
    """Download a generated PDF export file."""

    export_path = require_export_file(export_id)
    file_name = safe_file_name(fileName or export_id)

    return FileResponse(
        export_path,
        filename=file_name,
        media_type="application/pdf",
    )
