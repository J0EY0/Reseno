from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.schemas.model_configs import ApiFamily, ProviderKind
from app.services.model_metadata import (
    ModelMetadata,
    ensure_provider_model_metadata,
    resolve_model_metadata,
)
from app.services.thinking import ThinkingControl

DEFAULT_CONTEXT_WINDOW_TOKENS = 32768
DISCOVERY_TIMEOUT_SECONDS = 12


class ModelDiscoveryError(RuntimeError):
    """Raised when a provider cannot return a usable model list."""


@dataclass(frozen=True)
class ModelProvider:
    """Backend-owned provider manifest entry."""

    id: str
    label: str
    kind: ProviderKind
    api_family: ApiFamily | None
    icon_provider: str
    default_base_url: str
    official_url: str
    auth_required: bool
    supports_model_discovery: bool
    supports_custom_capabilities: bool
    supports_tools: bool = True
    supports_streaming: bool = True
    model_list_path: str = "/models"


@dataclass(frozen=True)
class DiscoveredModel:
    """One normalized model discovered from a provider."""

    id: str
    label: str
    context_window_tokens: int
    max_output_tokens: int | None
    supports_image: bool
    thinking_control: ThinkingControl
    metadata_source: str
    supports_tools: bool = True
    supports_streaming: bool = True


MODEL_PROVIDERS: tuple[ModelProvider, ...] = (
    ModelProvider(
        id="openai",
        label="OpenAI",
        kind="cloud",
        api_family="openai_responses",
        icon_provider="openai",
        default_base_url="https://api.openai.com/v1",
        official_url="https://platform.openai.com/docs/api-reference",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="anthropic",
        label="Anthropic",
        kind="cloud",
        api_family="anthropic_messages",
        icon_provider="anthropic",
        default_base_url="https://api.anthropic.com/v1",
        official_url="https://docs.anthropic.com/en/api/overview",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="google",
        label="Google Gemini",
        kind="cloud",
        api_family="google_gemini",
        icon_provider="google",
        default_base_url="https://generativelanguage.googleapis.com/v1",
        official_url="https://ai.google.dev/gemini-api/docs",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="deepseek",
        label="DeepSeek",
        kind="cloud",
        api_family="openai_compatible_chat",
        icon_provider="deepseek",
        default_base_url="https://api.deepseek.com",
        official_url="https://api-docs.deepseek.com",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="qwen",
        label="Qwen",
        kind="cloud",
        api_family="openai_compatible_chat",
        icon_provider="qwen",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        official_url=(
            "https://www.alibabacloud.com/help/en/model-studio/"
            "compatibility-of-openai-with-dashscope"
        ),
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="minimax",
        label="MiniMax",
        kind="cloud",
        api_family="openai_compatible_chat",
        icon_provider="minimax",
        default_base_url="https://api.minimaxi.com/v1",
        official_url="https://platform.minimax.io/docs",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="glm",
        label="Z.ai",
        kind="cloud",
        api_family="openai_compatible_chat",
        icon_provider="zhipuai",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        official_url="https://docs.bigmodel.cn/api-reference",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="moonshot",
        label="Moonshot AI",
        kind="cloud",
        api_family="openai_compatible_chat",
        icon_provider="moonshot",
        default_base_url="https://api.moonshot.ai/v1",
        official_url="https://platform.moonshot.ai/docs",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="xai",
        label="xAI",
        kind="cloud",
        api_family="openai_responses",
        icon_provider="xai",
        default_base_url="https://api.x.ai/v1",
        official_url="https://docs.x.ai/overview",
        auth_required=True,
        supports_model_discovery=True,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="ollama",
        label="Ollama",
        kind="local",
        api_family="openai_compatible_chat",
        icon_provider="ollama",
        default_base_url="http://localhost:11434/v1",
        official_url="",
        auth_required=False,
        supports_model_discovery=False,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="vllm",
        label="vLLM",
        kind="local",
        api_family="openai_compatible_chat",
        icon_provider="vllm",
        default_base_url="http://localhost:8000/v1",
        official_url="",
        auth_required=False,
        supports_model_discovery=False,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="sglang",
        label="SGLang",
        kind="local",
        api_family="openai_compatible_chat",
        icon_provider="sglang",
        default_base_url="http://localhost:30000/v1",
        official_url="",
        auth_required=False,
        supports_model_discovery=False,
        supports_custom_capabilities=False,
        model_list_path="/models",
    ),
    ModelProvider(
        id="custom-cloud",
        label="Custom Cloud API",
        kind="custom",
        api_family=None,
        icon_provider="openai",
        default_base_url="",
        official_url="",
        auth_required=True,
        supports_model_discovery=False,
        supports_custom_capabilities=True,
    ),
)

PROVIDERS_BY_ID = {provider.id: provider for provider in MODEL_PROVIDERS}
PROVIDER_ALIASES = {
    "kimi": "moonshot",
    "local": "ollama",
    "moonshotai": "moonshot",
    "ollma": "ollama",
    "z.ai": "glm",
    "zai": "glm",
    "zhipu": "glm",
    "zhipuai": "glm",
}


def list_model_providers() -> list[ModelProvider]:
    """Return provider manifest entries in display order."""

    return list(MODEL_PROVIDERS)


def get_model_provider(provider_id: str) -> ModelProvider | None:
    """Return one provider manifest entry."""

    normalized = provider_id.strip().lower()
    return PROVIDERS_BY_ID.get(PROVIDER_ALIASES.get(normalized, normalized))


def resolve_model_provider_base_url(
    provider_id: str,
    provider_kind: str,
    configured_url: str,
) -> str:
    """Return the backend-owned endpoint for official cloud providers."""

    provider = get_model_provider(provider_id)
    if provider_kind == "cloud" and provider is not None and provider.kind == "cloud":
        return provider.default_base_url

    return configured_url.strip()


def discover_provider_models(
    *,
    provider_id: str,
    api_family: ApiFamily,
    api_url: str,
    api_key: str,
) -> list[DiscoveredModel]:
    """Fetch and normalize models from a provider discovery endpoint."""

    provider = get_model_provider(provider_id)
    if provider is None or not provider.supports_model_discovery:
        raise ModelDiscoveryError("Provider does not support model discovery.")
    if provider.api_family != api_family:
        raise ModelDiscoveryError("Provider API family does not match.")
    if provider.auth_required and not api_key.strip():
        raise ModelDiscoveryError("Provider API key is required.")

    raw_models = _raw_discovered_models(
        provider=provider,
        api_family=api_family,
        api_url=api_url,
        api_key=api_key,
    )
    raw_model_ids = [_model_id_from_raw(raw) for raw in raw_models]
    ensure_provider_model_metadata(
        provider.id,
        [model_id for model_id in raw_model_ids if model_id],
    )
    normalized = [
        _normalize_discovered_model(provider.id, raw)
        for raw in raw_models
        if _model_id_from_raw(raw)
    ]
    filtered = [
        model
        for model in normalized
        if _is_text_generation_model(provider.id, model.id)
    ]

    return sorted(filtered, key=lambda item: item.id.lower())


def enrich_selected_model(
    *,
    provider_id: str,
    model_id: str,
    raw_model: dict[str, Any] | None = None,
) -> DiscoveredModel:
    """Return a model metadata snapshot for a selected model id."""

    return _normalize_discovered_model(
        provider_id,
        {"id": model_id, **(raw_model or {})},
    )


def _raw_discovered_models(
    *,
    provider: ModelProvider,
    api_family: ApiFamily,
    api_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    if api_family == "openai_responses":
        return _openai_models(provider, api_url, api_key)
    if api_family == "openai_compatible_chat":
        return _openai_compatible_models(provider, api_url, api_key)
    if api_family == "anthropic_messages":
        return _anthropic_models(provider, api_url, api_key)
    if api_family == "google_gemini":
        return _gemini_models(provider, api_url, api_key)

    raise ModelDiscoveryError("Unsupported API family.")


def _openai_models(
    provider: ModelProvider,
    api_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    return _models_from_data_response(
        _get_json(
            _model_list_url(provider, api_url),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key.strip()}",
            },
        ),
        "OpenAI-compatible provider returned an unsupported model list.",
    )


def _openai_compatible_models(
    provider: ModelProvider,
    api_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    return _models_from_data_response(
        _get_json(_model_list_url(provider, api_url), headers=headers),
        "Provider returned an unsupported model list.",
    )


def _models_from_data_response(
    payload: dict[str, Any],
    error_message: str,
) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    models = payload.get("models")
    if isinstance(models, list):
        return [item for item in models if isinstance(item, dict)]

    raise ModelDiscoveryError(error_message)


def _model_list_url(provider: ModelProvider, api_url: str) -> str:
    return (
        f"{_normalized_base_url(api_url)}/"
        f"{provider.model_list_path.strip().lstrip('/')}"
    )


def _anthropic_models(
    provider: ModelProvider,
    api_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    payload = _get_json(
        _model_list_url(provider, api_url),
        headers={
            "Accept": "application/json",
            "x-api-key": api_key.strip(),
            "anthropic-version": "2023-06-01",
        },
    )
    data = payload.get("data")
    if not isinstance(data, list):
        raise ModelDiscoveryError("Anthropic returned an unsupported model list.")

    return [item for item in data if isinstance(item, dict)]


def _gemini_models(
    provider: ModelProvider,
    api_url: str,
    api_key: str,
) -> list[dict[str, Any]]:
    payload = _get_json(
        _model_list_url(provider, api_url),
        headers={
            "Accept": "application/json",
            "x-goog-api-key": api_key.strip(),
        },
    )
    models = payload.get("models")
    if not isinstance(models, list):
        raise ModelDiscoveryError("Gemini returned an unsupported model list.")

    return [item for item in models if isinstance(item, dict)]


def _get_json(url: str, *, headers: dict[str, str]) -> dict[str, Any]:
    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=DISCOVERY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ModelDiscoveryError("Model discovery failed.") from exc

    if not isinstance(payload, dict):
        raise ModelDiscoveryError("Provider returned an unsupported response.")

    return payload


def _normalize_discovered_model(
    provider_id: str,
    raw: dict[str, Any],
) -> DiscoveredModel:
    model_id = _model_id_from_raw(raw)
    provider_context = _provider_context_limit(provider_id, raw)
    provider_output = _positive_int(
        raw.get("max_output_tokens")
        or raw.get("max_tokens")
        or raw.get("maxOutputTokens")
        or raw.get("outputTokenLimit")
        or raw.get("output_token_limit"),
    )
    metadata_source = "provider" if provider_context or provider_output else "fallback"
    litellm_metadata = resolve_model_metadata(provider_id, model_id)
    if provider_context is None and litellm_metadata is not None:
        provider_context = litellm_metadata.context_window_tokens
        metadata_source = "litellm" if provider_context else metadata_source
    if provider_output is None and litellm_metadata is not None:
        provider_output = litellm_metadata.max_output_tokens
        metadata_source = "litellm" if provider_output else metadata_source

    if provider_context is None:
        provider_context = DEFAULT_CONTEXT_WINDOW_TOKENS
        metadata_source = "fallback"

    return DiscoveredModel(
        id=model_id,
        label=model_id,
        context_window_tokens=provider_context,
        max_output_tokens=provider_output,
        supports_image=_supports_image(
            provider_id,
            model_id,
            raw,
            litellm_metadata,
        ),
        thinking_control=_thinking_control(
            provider_id,
            model_id,
            raw,
            litellm_metadata,
        ),
        metadata_source=metadata_source,
        supports_tools=_supports_tools(provider_id, model_id, raw, litellm_metadata),
        supports_streaming=_supports_streaming(
            provider_id,
            model_id,
            raw,
            litellm_metadata,
        ),
    )


def _provider_context_limit(
    provider_id: str,
    raw: dict[str, Any],
) -> int | None:
    """Return only context fields whose meaning matches the provider kind."""

    # Prefer an explicit input limit when both shapes are present. Providers
    # such as Gemini expose input and output limits independently, whereas
    # generic `context_length` fields describe one shared total context.
    for key in ("max_input_tokens", "inputTokenLimit", "input_token_limit"):
        if value := _positive_int(raw.get(key)):
            return value

    provider = get_model_provider(provider_id)
    if provider is not None and provider.kind != "cloud":
        for key in ("context_window", "context_length", "max_context_length"):
            if value := _positive_int(raw.get(key)):
                return value
    return None


def _model_id_from_raw(raw: dict[str, Any]) -> str:
    for key in ("id", "name", "model", "model_name"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            model_id = value.strip()
            return model_id.removeprefix("models/")

    return ""


def _is_text_generation_model(provider_id: str, model_id: str) -> bool:
    lowered = model_id.lower()
    blocked_markers = (
        "embedding",
        "rerank",
        "moderation",
        "whisper",
        "tts",
        "speech",
        "asr",
        "audio",
        "dall-e",
        "image-generation",
        "glm-image",
        "cogview",
        "cogvideo",
        "video",
        "ocr",
    )
    if any(marker in lowered for marker in blocked_markers):
        return False
    if provider_id == "google" and "aqa" in lowered:
        return False

    return True


def _supports_image(
    provider_id: str,
    model_id: str,
    raw: dict[str, Any],
    metadata: ModelMetadata | None,
) -> bool:
    lowered = model_id.lower()
    heuristic = False
    if provider_id == "google":
        methods = raw.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" not in methods:
            heuristic = False
        else:
            heuristic = lowered.startswith("gemini-")
    elif provider_id == "openai":
        heuristic = lowered.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4"))
    elif provider_id == "anthropic":
        heuristic = lowered.startswith("claude-3") or lowered.startswith("claude-")
    elif provider_id == "qwen":
        heuristic = "vl" in lowered or "omni" in lowered
    elif provider_id == "glm":
        heuristic = "-v" in lowered or lowered.endswith("v") or "vision" in lowered
    elif provider_id == "minimax":
        heuristic = "vl" in lowered or "vision" in lowered

    value = _metadata_bool(
        metadata.supports_image if metadata is not None else None,
        heuristic,
    )
    explicit = _explicit_bool(raw, "supports_image", "supportsImage", "supports_vision")
    return explicit if explicit is not None else value


def _thinking_control(
    provider_id: str,
    model_id: str,
    raw: dict[str, Any],
    metadata: ModelMetadata | None,
) -> ThinkingControl:
    if provider_id == "minimax" and model_id.casefold() == "minimax-m3":
        return "native_auto"

    if provider_id == "anthropic":
        # Anthropic's Models API distinguishes legacy manual thinking from
        # adaptive thinking. Preserve that protocol distinction so the Adapter
        # never infers a wire shape from a generic capability badge.
        adaptive = _nested_bool(
            raw,
            "capabilities",
            "thinking",
            "types",
            "adaptive",
            "supported",
        )
        if adaptive is True:
            return "native_auto"
        enabled = _nested_bool(
            raw,
            "capabilities",
            "thinking",
            "types",
            "enabled",
            "supported",
        )
        return "native_budget" if enabled is True else "none"

    explicit = _explicit_bool(raw, "supports_reasoning", "supportsThinking")
    supported = (
        explicit
        if explicit is not None
        else metadata.supports_thinking
        if metadata is not None
        else None
    )
    if supported is not True:
        return "none"

    # DashScope exposes a verified per-request `enable_thinking` switch. Other
    # official cloud providers either think by model/default or are projected
    # by their Adapter without a generic explicit toggle.
    return "native_auto" if provider_id == "qwen" else "provider_default"


def _nested_bool(value: object, *path: str) -> bool | None:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, bool) else None


def _supports_tools(
    provider_id: str,
    model_id: str,
    raw: dict[str, Any],
    metadata: ModelMetadata | None,
) -> bool:
    """Return whether the selected model can drive the agent tool loop."""

    provider = get_model_provider(provider_id)
    default = provider.supports_tools if provider is not None else True
    value = _metadata_bool(
        metadata.supports_tools if metadata is not None else None,
        default,
    )
    explicit = _explicit_bool(
        raw,
        "supports_tools",
        "supportsTools",
        "supports_function_calling",
        "supportsFunctionCalling",
    )
    return explicit if explicit is not None else value


def _supports_streaming(
    provider_id: str,
    model_id: str,
    raw: dict[str, Any],
    metadata: ModelMetadata | None,
) -> bool:
    """Return whether the selected model can stream final agent responses."""

    provider = get_model_provider(provider_id)
    default = provider.supports_streaming if provider is not None else True
    value = _metadata_bool(
        metadata.supports_streaming if metadata is not None else None,
        default,
    )
    explicit = _explicit_bool(raw, "supports_streaming", "supportsStreaming")
    return explicit if explicit is not None else value


def _metadata_bool(value: bool | None, fallback: bool) -> bool:
    return value if value is not None else fallback


def _explicit_bool(raw: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, bool):
            return value

    return None


def _normalized_base_url(api_url: str) -> str:
    normalized = api_url.strip().rstrip("/")
    if not normalized:
        raise ModelDiscoveryError("Provider API URL is required.")
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")].rstrip("/")
    return normalized


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
