from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.schemas.common import ApiResponse, ok_response
from app.schemas.exports import (
    ExportResumeImagesRequest,
    ExportResumeImagesResponse,
    ExportResumePdfRequest,
    ExportResumePdfResponse,
    ExportResumeRenderRequest,
)
from app.services.auth_tokens import format_token_expiry
from app.services.pdf import (
    create_export_id,
    require_export_file,
    require_image_export_file,
    safe_file_name,
    safe_image_file_name,
    write_resume_images,
    write_resume_pdf,
)
from app.services.resumes import load_resume, load_resume_version

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _require_resume_for_export(request: ExportResumeRenderRequest) -> None:
    """Ensure the requested current or historical resume version exists."""

    try:
        if request.version_id:
            load_resume_version(request.resume_id, request.version_id)
        else:
            load_resume(request.resume_id)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found for export.",
        ) from exc


def _render_auth_kwargs(http_request: Request) -> dict[str, str | None]:
    """Forward the current auth session to the internal frontend renderer."""

    auth_payload = getattr(http_request.state, "auth_payload", None)
    return {
        "access_token": getattr(http_request.state, "auth_token", None),
        "token_expires_at": (
            format_token_expiry(auth_payload.expires_at) if auth_payload else None
        ),
        "username": auth_payload.subject if auth_payload else None,
    }


@router.post("/resume-pdf", response_model=ApiResponse[ExportResumePdfResponse])
def export_resume_pdf(
    request: ExportResumePdfRequest,
    http_request: Request,
) -> ApiResponse[ExportResumePdfResponse]:
    """Generate a PDF export for a saved resume."""

    _require_resume_for_export(request)

    export_id = create_export_id()
    file_name = safe_file_name(request.file_name_seed)
    write_resume_pdf(
        export_id,
        request,
        **_render_auth_kwargs(http_request),
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


@router.post(
    "/resume-images",
    response_model=ApiResponse[ExportResumeImagesResponse],
)
def export_resume_images(
    request: ExportResumeImagesRequest,
    http_request: Request,
) -> ApiResponse[ExportResumeImagesResponse]:
    """Export each saved resume page as PNG, archiving multi-page output."""

    _require_resume_for_export(request)
    export_id = create_export_id()
    result = write_resume_images(
        export_id,
        request,
        **_render_auth_kwargs(http_request),
    )
    file_name = safe_image_file_name(
        request.file_name_seed,
        is_archive=result.is_archive,
    )
    download_query = urlencode({"fileName": file_name})

    return ok_response(
        ExportResumeImagesResponse(
            exportId=export_id,
            downloadUrl=(f"/api/exports/image-download/{export_id}?{download_query}"),
            fileName=file_name,
            expiresAt=None,
            pageCount=result.page_count,
            isArchive=result.is_archive,
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


@router.get("/image-download/{export_id}")
def download_image_export(
    export_id: str,
    fileName: str | None = None,
) -> FileResponse:
    """Download a generated PNG or multi-page ZIP image export."""

    export_path = require_image_export_file(export_id)
    is_archive = export_path.suffix.lower() == ".zip"
    file_name = safe_image_file_name(
        fileName or export_id,
        is_archive=is_archive,
    )

    return FileResponse(
        export_path,
        filename=file_name,
        media_type="application/zip" if is_archive else "image/png",
    )
