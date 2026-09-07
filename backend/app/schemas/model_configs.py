from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.services.thinking import ThinkingMode

ApiFamily = Literal[
    "openai_responses",
    "openai_compatible_chat",
    "anthropic_messages",
    "google_gemini",
]
ProviderKind = Literal["cloud", "local", "custom"]
# Model-config values cross a JSON/JavaScript client before reaching SQLite.
# Capping user overrides at Number.MAX_SAFE_INTEGER preserves the exact value
# across that full interface and remains comfortably inside SQLite's int64.
MAX_USER_MAX_TOKENS = 9_007_199_254_740_991


class ModelProviderResponse(BaseModel):
    """One backend-owned provider manifest entry."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    kind: ProviderKind
    api_family: ApiFamily | None = Field(alias="apiFamily")
    icon_provider: str = Field(alias="iconProvider")
    default_base_url: str = Field(alias="defaultBaseUrl")
    official_url: str = Field(alias="officialUrl")
    auth_required: bool = Field(alias="authRequired")
    supports_model_discovery: bool = Field(alias="supportsModelDiscovery")
    supports_custom_capabilities: bool = Field(alias="supportsCustomCapabilities")
    supports_tools: bool = Field(alias="supportsTools")
    supports_streaming: bool = Field(alias="supportsStreaming")


class ModelProvidersResponse(BaseModel):
    """Collection response for model provider manifest entries."""

    providers: list[ModelProviderResponse]


class DiscoveredModelResponse(BaseModel):
    """One model option discovered from a provider API."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    label: str
    context_window_tokens: int = Field(alias="contextWindowTokens")
    max_output_tokens: int | None = Field(default=None, alias="maxOutputTokens")
    supports_image: bool = Field(alias="supportsImage")
    supports_thinking: bool = Field(alias="supportsThinking")
    available_thinking_modes: list[ThinkingMode] = Field(
        alias="availableThinkingModes",
        description=(
            "User-selectable reasoning modes proven by normalized provider "
            "metadata; off is absent when explicit disabling is unverified."
        ),
    )
    supports_tools: bool = Field(alias="supportsTools")
    supports_streaming: bool = Field(alias="supportsStreaming")
    metadata_source: str = Field(alias="metadataSource")


class DiscoverModelsRequest(BaseModel):
    """Provider credentials used for one non-persistent model discovery request."""

    model_config = ConfigDict(populate_by_name=True)

    provider: str
    api_family: ApiFamily | None = Field(default=None, alias="apiFamily")
    api_url: str = Field(alias="apiUrl")
    api_key: str | None = Field(default=None, alias="apiKey")
    client_id: str | None = Field(default=None, alias="configId")
    refresh: bool = False


class DiscoverModelsResponse(BaseModel):
    """Model discovery response, optionally backed by the local provider cache."""

    model_config = ConfigDict(populate_by_name=True)

    models: list[DiscoveredModelResponse]
    source: str = "provider"


class ModelConfigUpsertRequest(BaseModel):
    """Model config data accepted from the frontend settings UI."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str | None = Field(default=None, alias="id")
    provider: str
    api_family: ApiFamily = Field(alias="apiFamily")
    provider_kind: ProviderKind = Field(alias="providerKind")
    nickname: str = ""
    api_key: str | None = Field(default=None, alias="apiKey")
    model: str
    api_url: str = Field(alias="apiUrl")
    temperature: float | None = None
    top_p: float | None = Field(default=None, alias="topP")
    max_tokens: int | None = Field(
        default=None,
        alias="maxTokens",
        strict=True,
        gt=0,
        le=MAX_USER_MAX_TOKENS,
        description=(
            "Optional per-request output-token override; null delegates the "
            "limit to Reseno's automatic runtime policy."
        ),
    )
    context_window_tokens: int | None = Field(
        default=None,
        alias="contextWindowTokens",
    )
    supports_image: bool = Field(default=False, alias="supportsImage")
    supports_thinking: bool = Field(default=False, alias="supportsThinking")
    thinking_mode: ThinkingMode = Field(
        default="auto",
        alias="thinkingMode",
        description=(
            "Reasoning preference for this model config. Off is validated "
            "against the selected model's explicit disable capability."
        ),
    )
    supports_tools: bool = Field(default=True, alias="supportsTools")
    supports_streaming: bool = Field(default=True, alias="supportsStreaming")


class ModelConfigBulkDeleteRequest(BaseModel):
    """Unique model config ids to soft-delete in one operation."""

    ids: list[str] = Field(min_length=1)

    @field_validator("ids")
    @classmethod
    def validate_ids(cls, ids: list[str]) -> list[str]:
        normalized_ids = [client_id.strip() for client_id in ids]
        if any(not client_id for client_id in normalized_ids):
            raise PydanticCustomError(
                "model_config_id_empty",
                "Model config ids must not be empty.",
            )
        if len(set(normalized_ids)) != len(normalized_ids):
            raise PydanticCustomError(
                "model_config_ids_duplicate",
                "Model config ids must be unique.",
            )
        return normalized_ids


class ModelConfigBulkDeleteResponse(BaseModel):
    """Model config ids accepted by a successful bulk delete."""

    ids: list[str]


class ModelConfigResponse(BaseModel):
    """Model config data returned without plaintext API keys."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    provider: str
    provider_label: str = Field(alias="providerLabel")
    icon_provider: str = Field(alias="iconProvider")
    api_family: ApiFamily = Field(alias="apiFamily")
    provider_kind: ProviderKind = Field(alias="providerKind")
    nickname: str
    api_key_preview: str = Field(alias="apiKeyPreview")
    model: str
    api_url: str = Field(alias="apiUrl")
    temperature: float | None
    top_p: float | None = Field(alias="topP")
    max_tokens: int | None = Field(alias="maxTokens")
    context_window_tokens: int = Field(alias="contextWindowTokens")
    supports_image: bool = Field(alias="supportsImage")
    supports_thinking: bool = Field(alias="supportsThinking")
    thinking_mode: ThinkingMode = Field(alias="thinkingMode")
    available_thinking_modes: list[ThinkingMode] = Field(
        alias="availableThinkingModes",
    )
    supports_tools: bool = Field(alias="supportsTools")
    supports_streaming: bool = Field(alias="supportsStreaming")


class ModelConfigsResponse(BaseModel):
    """Collection response for enabled model configs."""

    configs: list[ModelConfigResponse]
