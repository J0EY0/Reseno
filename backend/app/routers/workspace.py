from typing import Any

from fastapi import APIRouter, Query

from app.schemas.common import ApiResponse, ok_response
from app.schemas.workspace import (
    WorkspaceSaveRequest,
    WorkspaceSaveResponse,
    WorkspaceVersionResponse,
    WorkspaceVersionsResponse,
)
from app.services.workspace import (
    list_workspace_versions,
    load_workspace,
    load_workspace_version,
    save_workspace,
)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/bootstrap", response_model=ApiResponse[dict[str, Any]])
def get_workspace_bootstrap(
    locale: str = Query(default="zh"),
) -> ApiResponse[dict[str, Any]]:
    """Return the current workspace bootstrap payload."""

    return ok_response(load_workspace(locale))


@router.put("/snapshot", response_model=ApiResponse[WorkspaceSaveResponse])
def put_workspace_snapshot(
    request: WorkspaceSaveRequest,
    locale: str = Query(default="zh"),
) -> ApiResponse[WorkspaceSaveResponse]:
    """Persist a workspace snapshot from the frontend."""

    result = save_workspace(locale, request.snapshot)

    return ok_response(WorkspaceSaveResponse.model_validate(result))


@router.get("/versions", response_model=ApiResponse[WorkspaceVersionsResponse])
def get_workspace_versions(
    locale: str = Query(default="zh"),
) -> ApiResponse[WorkspaceVersionsResponse]:
    """Return available workspace version summaries."""

    return ok_response(
        WorkspaceVersionsResponse.model_validate(
            {"versions": list_workspace_versions(locale)}
        )
    )


@router.get(
    "/versions/{version_id}",
    response_model=ApiResponse[WorkspaceVersionResponse],
)
def get_workspace_version(
    version_id: str,
    locale: str = Query(default="zh"),
) -> ApiResponse[WorkspaceVersionResponse]:
    """Return a reconstructed workspace snapshot for one version."""

    return ok_response(
        WorkspaceVersionResponse.model_validate(
            {
                "versionId": version_id,
                "snapshot": load_workspace_version(locale, version_id),
            }
        )
    )
