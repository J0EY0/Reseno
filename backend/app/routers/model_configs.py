from contextlib import closing

from fastapi import APIRouter, HTTPException, status

from app.db.connection import connect
from app.schemas.common import ApiResponse, ok_response
from app.schemas.model_configs import (
    ModelConfigBulkDeleteRequest,
    ModelConfigBulkDeleteResponse,
    ModelConfigResponse,
    ModelConfigsResponse,
    ModelConfigUpsertRequest,
)
from app.services.model_configs import (
    ModelConfigNotFoundError,
    delete_llm_config,
    delete_llm_configs,
    list_llm_configs,
    upsert_llm_config,
)

router = APIRouter(prefix="/api/model-configs", tags=["model-configs"])


@router.get("", response_model=ApiResponse[ModelConfigsResponse])
def get_model_configs() -> ApiResponse[ModelConfigsResponse]:
    """Return all enabled model configs with masked API key previews."""

    return ok_response(ModelConfigsResponse(configs=list_llm_configs()))


@router.post("", response_model=ApiResponse[ModelConfigResponse])
def post_model_config(
    request: ModelConfigUpsertRequest,
) -> ApiResponse[ModelConfigResponse]:
    """Create or update one encrypted model config."""

    with closing(connect()) as conn:
        try:
            response = upsert_llm_config(conn, request)
        except ValueError as exc:
            detail = str(exc) or "BAD_REQUEST"
            if detail not in {
                "MODEL_DISCOVERY_FAILED",
                "MODEL_CONFIG_INVALID_PROVIDER",
                "MODEL_CONFIG_MODEL_NOT_DISCOVERED",
                "MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT",
                "MODEL_CONFIG_THINKING_MODE_UNSUPPORTED",
            }:
                detail = "BAD_REQUEST"
            raise HTTPException(status_code=400, detail=detail) from exc

    return ok_response(response)


@router.post(
    "/bulk-delete",
    response_model=ApiResponse[ModelConfigBulkDeleteResponse],
)
def post_model_configs_bulk_delete(
    request: ModelConfigBulkDeleteRequest,
) -> ApiResponse[ModelConfigBulkDeleteResponse]:
    """Soft-delete a validated set of model configs atomically."""

    with closing(connect()) as conn:
        try:
            deleted_ids = delete_llm_configs(conn, request.ids)
        except ModelConfigNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="MODEL_CONFIG_NOT_FOUND",
            ) from exc

    return ok_response(ModelConfigBulkDeleteResponse(ids=deleted_ids))


@router.delete("/{client_id}", response_model=ApiResponse[dict[str, str]])
def delete_model_config(client_id: str) -> ApiResponse[dict[str, str]]:
    """Disable one model config by frontend client id."""

    with closing(connect()) as conn:
        delete_llm_config(conn, client_id)

    return ok_response({"id": client_id})
