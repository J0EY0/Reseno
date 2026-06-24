from fastapi import APIRouter, HTTPException

from app.db.connection import connect
from app.schemas.common import ApiResponse, ok_response
from app.schemas.model_configs import (
    ModelConfigResponse,
    ModelConfigsResponse,
    ModelConfigUpsertRequest,
)
from app.services.model_configs import (
    delete_llm_config,
    list_llm_configs,
    upsert_llm_config,
)

router = APIRouter(prefix="/api/model-configs", tags=["model-configs"])


@router.get("", response_model=ApiResponse[ModelConfigsResponse])
def get_model_configs() -> ApiResponse[ModelConfigsResponse]:
    """Return all enabled model configs with masked API key previews."""

    with connect() as conn:
        configs = list_llm_configs(conn)

    return ok_response(ModelConfigsResponse(configs=configs))


@router.post("", response_model=ApiResponse[ModelConfigResponse])
def post_model_config(
    request: ModelConfigUpsertRequest,
) -> ApiResponse[ModelConfigResponse]:
    """Create or update one encrypted model config."""

    with connect() as conn:
        try:
            response = upsert_llm_config(conn, request)
        except ValueError as exc:
            detail = str(exc) or "BAD_REQUEST"
            if detail not in {
                "MODEL_DISCOVERY_FAILED",
                "MODEL_CONFIG_INVALID_PROVIDER",
                "MODEL_CONFIG_MODEL_NOT_DISCOVERED",
            }:
                detail = "BAD_REQUEST"
            raise HTTPException(status_code=400, detail=detail) from exc

    return ok_response(response)


@router.delete("/{client_id}", response_model=ApiResponse[dict[str, str]])
def delete_model_config(client_id: str) -> ApiResponse[dict[str, str]]:
    """Disable one model config by frontend client id."""

    with connect() as conn:
        delete_llm_config(conn, client_id)

    return ok_response({"id": client_id})
