from fastapi import APIRouter, HTTPException

from app.db.connection import connect
from app.schemas.common import ApiResponse, ok_response
from app.schemas.model_configs import (
    DiscoveredModelResponse,
    DiscoverModelsRequest,
    DiscoverModelsResponse,
    ModelProviderResponse,
    ModelProvidersResponse,
)
from app.services.llm_secrets import decrypt_api_key
from app.services.model_discovery_cache import (
    read_cached_provider_models,
    write_cached_provider_models,
)
from app.services.model_providers import (
    ModelDiscoveryError,
    discover_provider_models,
    get_model_provider,
    list_model_providers,
)

router = APIRouter(prefix="/api/model-providers", tags=["model-providers"])


@router.get("", response_model=ApiResponse[ModelProvidersResponse])
def get_model_providers() -> ApiResponse[ModelProvidersResponse]:
    """Return the backend-owned provider manifest."""

    providers = [
        ModelProviderResponse(
            id=provider.id,
            label=provider.label,
            kind=provider.kind,
            apiFamily=provider.api_family,
            iconProvider=provider.icon_provider,
            defaultBaseUrl=provider.default_base_url,
            officialUrl=provider.official_url,
            authRequired=provider.auth_required,
            supportsModelDiscovery=provider.supports_model_discovery,
            supportsCustomCapabilities=provider.supports_custom_capabilities,
            supportsTools=provider.supports_tools,
            supportsStreaming=provider.supports_streaming,
        )
        for provider in list_model_providers()
    ]

    return ok_response(ModelProvidersResponse(providers=providers))


@router.post("/discover-models", response_model=ApiResponse[DiscoverModelsResponse])
def discover_models(
    request: DiscoverModelsRequest,
) -> ApiResponse[DiscoverModelsResponse]:
    """Discover models for one provider without persisting credentials."""

    provider = get_model_provider(request.provider)
    if (
        provider is None
        or provider.kind != "cloud"
        or not provider.supports_model_discovery
    ):
        raise HTTPException(status_code=400, detail="MODEL_DISCOVERY_FAILED")

    api_family = request.api_family or provider.api_family
    if api_family is None or api_family != provider.api_family:
        raise HTTPException(status_code=400, detail="MODEL_DISCOVERY_FAILED")

    if not request.refresh:
        return ok_response(
            DiscoverModelsResponse(
                models=[
                    DiscoveredModelResponse(
                        id=model.id,
                        label=model.label,
                        contextWindowTokens=model.context_window_tokens,
                        maxOutputTokens=model.max_output_tokens,
                        supportsImage=model.supports_image,
                        supportsThinking=model.thinking_control != "none",
                        supportsTools=model.supports_tools,
                        supportsStreaming=model.supports_streaming,
                        metadataSource=model.metadata_source,
                    )
                    for model in (read_cached_provider_models(provider.id) or [])
                ],
                source="cache",
            ),
        )

    api_key = (request.api_key or "").strip()
    if not api_key and request.client_id:
        api_key = _saved_api_key(request.client_id)
    if provider.auth_required and not api_key:
        raise HTTPException(status_code=400, detail="MODEL_DISCOVERY_FAILED")

    try:
        models = discover_provider_models(
            provider_id=provider.id,
            api_family=api_family,
            # Discovery cache is keyed by official cloud provider. Custom-cloud
            # and local endpoints do not participate, so use the backend manifest
            # route instead of letting request-scoped URLs poison the cache.
            api_url=provider.default_base_url,
            api_key=api_key,
        )
    except ModelDiscoveryError as exc:
        raise HTTPException(
            status_code=400,
            detail="MODEL_DISCOVERY_FAILED",
        ) from exc

    if not models:
        raise HTTPException(status_code=400, detail="MODEL_DISCOVERY_EMPTY")

    write_cached_provider_models(provider.id, models)

    return ok_response(
        DiscoverModelsResponse(
            models=[
                DiscoveredModelResponse(
                    id=model.id,
                    label=model.label,
                    contextWindowTokens=model.context_window_tokens,
                    maxOutputTokens=model.max_output_tokens,
                    supportsImage=model.supports_image,
                    supportsThinking=model.thinking_control != "none",
                    supportsTools=model.supports_tools,
                    supportsStreaming=model.supports_streaming,
                    metadataSource=model.metadata_source,
                )
                for model in models
            ],
            source="provider",
        ),
    )


def _saved_api_key(client_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT encrypted_api_key
            FROM llm_configs
            WHERE client_id = ? AND enabled = 1
            """,
            (client_id,),
        ).fetchone()

    if row is None or not row["encrypted_api_key"]:
        return ""

    return decrypt_api_key(row["encrypted_api_key"])
