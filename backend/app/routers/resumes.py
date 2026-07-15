from typing import Any, Literal

from fastapi import APIRouter, Query

from app.schemas.common import ApiResponse, ok_response
from app.schemas.resumes import (
    ResumeCreateRequest,
    ResumeDeleteResponse,
    ResumeDetailResponse,
    ResumeListResponse,
    ResumeSaveRequest,
    ResumeTrashEmptyResponse,
    ResumeVersionsResponse,
)
from app.services.workspace import (
    create_resume,
    delete_resume_forever,
    duplicate_resume,
    empty_resume_trash,
    list_resume_versions,
    list_resumes,
    load_resume,
    load_resume_version,
    restore_resume,
    save_resume,
    trash_resume,
)

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


@router.get("", response_model=ApiResponse[ResumeListResponse])
def get_resumes(
    status_filter: Literal["active", "deleted"] = Query(
        default="active",
        alias="status",
    ),
) -> ApiResponse[ResumeListResponse]:
    """Return active resume items or deleted resume previews."""

    return ok_response(ResumeListResponse.model_validate(list_resumes(status_filter)))


@router.post("", response_model=ApiResponse[ResumeDetailResponse])
def post_resume(
    request: ResumeCreateRequest,
) -> ApiResponse[ResumeDetailResponse]:
    """Create a backend-owned empty resume."""

    return ok_response(
        ResumeDetailResponse.model_validate(
            create_resume(
                request.model_dump(by_alias=True, exclude_unset=True),
            )
        )
    )


@router.delete("/trash", response_model=ApiResponse[ResumeTrashEmptyResponse])
def delete_resume_trash() -> ApiResponse[ResumeTrashEmptyResponse]:
    """Physically delete every resume in the recycle bin."""

    return ok_response(
        ResumeTrashEmptyResponse.model_validate(empty_resume_trash())
    )


@router.get("/{resume_id}", response_model=ApiResponse[ResumeDetailResponse])
def get_resume(resume_id: str) -> ApiResponse[ResumeDetailResponse]:
    """Return the current detail for one active resume."""

    return ok_response(ResumeDetailResponse.model_validate(load_resume(resume_id)))


@router.put("/{resume_id}", response_model=ApiResponse[ResumeDetailResponse])
def put_resume(
    resume_id: str,
    request: ResumeSaveRequest,
) -> ApiResponse[ResumeDetailResponse]:
    """Persist a full resume update."""

    return ok_response(
        ResumeDetailResponse.model_validate(
            save_resume(
                resume_id,
                request.model_dump(by_alias=True, exclude_unset=True),
            )
        )
    )


@router.post("/{resume_id}/duplicate", response_model=ApiResponse[ResumeDetailResponse])
def post_resume_duplicate(
    resume_id: str,
    locale: Literal["zh", "en"] = Query(default="en"),
) -> ApiResponse[ResumeDetailResponse]:
    """Create an independent copy of one active resume."""

    return ok_response(
        ResumeDetailResponse.model_validate(duplicate_resume(resume_id, locale))
    )


@router.post("/{resume_id}/trash", response_model=ApiResponse[dict[str, Any]])
def post_resume_trash(resume_id: str) -> ApiResponse[dict[str, Any]]:
    """Move one active resume into the recycle bin."""

    return ok_response(trash_resume(resume_id))


@router.post("/{resume_id}/restore", response_model=ApiResponse[ResumeDetailResponse])
def post_resume_restore(resume_id: str) -> ApiResponse[ResumeDetailResponse]:
    """Restore one deleted resume."""

    return ok_response(ResumeDetailResponse.model_validate(restore_resume(resume_id)))


@router.delete("/{resume_id}", response_model=ApiResponse[ResumeDeleteResponse])
def delete_resume(resume_id: str) -> ApiResponse[ResumeDeleteResponse]:
    """Physically delete one already-deleted resume."""

    return ok_response(
        ResumeDeleteResponse.model_validate(delete_resume_forever(resume_id))
    )


@router.get("/{resume_id}/versions", response_model=ApiResponse[ResumeVersionsResponse])
def get_resume_versions(resume_id: str) -> ApiResponse[ResumeVersionsResponse]:
    """Return version summaries for one resume."""

    return ok_response(
        ResumeVersionsResponse.model_validate(list_resume_versions(resume_id))
    )


@router.get(
    "/{resume_id}/versions/{version_id}",
    response_model=ApiResponse[ResumeDetailResponse],
)
def get_resume_version(
    resume_id: str,
    version_id: str,
) -> ApiResponse[ResumeDetailResponse]:
    """Return one historical version for one resume."""

    return ok_response(
        ResumeDetailResponse.model_validate(load_resume_version(resume_id, version_id))
    )
