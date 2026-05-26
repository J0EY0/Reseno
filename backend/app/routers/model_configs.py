from fastapi import APIRouter

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
        response = upsert_llm_config(conn, request)

    return ok_response(response)


@router.delete("/{client_id}", response_model=ApiResponse[dict[str, str]])
def delete_model_config(client_id: str) -> ApiResponse[dict[str, str]]:
    """Disable one model config by frontend client id."""

    with connect() as conn:
        delete_llm_config(conn, client_id)

    return ok_response({"id": client_id})
