import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings

MODEL_METADATA_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
MODEL_METADATA_CACHE_NAME = "model-metadata/litellm_context_windows.json"
MODEL_METADATA_FETCH_TIMEOUT_SECONDS = 1.5
MODEL_METADATA_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MODEL_METADATA_CACHE_VERSION = 1
MODEL_METADATA_CACHE_SOURCE = "litellm:model_prices_and_context_window"

LITELLM_PROVIDER_ALIASES: dict[str, set[str]] = {
    "openai": {"openai"},
    "anthropic": {"anthropic"},
    "google": {"gemini"},
    "deepseek": {"deepseek"},
    "qwen": {"dashscope", "qwen"},
    "minimax": {"minimax"},
    "glm": {"bigmodel", "zhipu", "zhipuai"},
    "moonshot": {"moonshot"},
    "xai": {"xai"},
}

_CATALOG_CACHE: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelMetadata:
    """LiteLLM model metadata relevant to ResuMate runtime limits."""

    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_image: bool | None = None
    supports_thinking: bool | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None


def resolve_model_metadata(provider: str, model: str) -> ModelMetadata | None:
    """Return cached LiteLLM-derived metadata for one provider/model pair."""

    provider_key = provider.strip().lower()
    model_key = model.strip()
    if not provider_key or not model_key:
        return None

    cache = _load_cache()
    provider_models = _cache_provider_models(cache, provider_key)
    if not provider_models:
        return None

    normalized_model = _normalize_model_name(model_key)
    for cached_model, value in provider_models.items():
        if not isinstance(value, dict):
            continue
        if _normalize_model_name(cached_model) == normalized_model:
            return _metadata_from_lightweight_item(value)

    return None


def ensure_model_metadata_cache() -> bool:
    """Ensure the lightweight LiteLLM metadata cache exists when possible."""

    cache_path = _cache_path()
    cached = _read_cache(cache_path) if cache_path.exists() else {}
    if cached and _cache_is_fresh(cache_path):
        _set_memory_cache(cached)
        return True

    return refresh_model_metadata_cache() or bool(cached)


def ensure_provider_model_metadata(provider: str, model_ids: list[str]) -> bool:
    """Refresh one provider's lightweight metadata when current cache misses models.

    Provider model discovery should not fail because GitHub/LiteLLM is down. This
    helper therefore returns a best-effort boolean and never raises for refresh
    failures; callers should still return provider-discovered models.
    """

    provider_key = provider.strip().lower()
    normalized_targets = {
        _normalize_model_name(model_id)
        for model_id in model_ids
        if model_id.strip()
    }
    if not provider_key or not normalized_targets:
        return False

    cache_path = _cache_path()
    cache = _load_cache()
    provider_models = _cache_provider_models(cache, provider_key)
    cached_names = {
        _normalize_model_name(model_id)
        for model_id in provider_models
    }
    has_miss = not normalized_targets.issubset(cached_names)
    if provider_models and not has_miss and _cache_is_fresh(cache_path):
        return True

    return refresh_model_metadata_cache(provider=provider_key)


def refresh_model_metadata_cache(provider: str | None = None) -> bool:
    """Fetch LiteLLM metadata and persist only ResuMate's lightweight subset."""

    raw_catalog = _fetch_catalog()
    if not raw_catalog:
        return False

    provider_key = provider.strip().lower() if provider else None
    existing = _load_cache()
    if provider_key:
        provider_models = _provider_models_from_catalog(raw_catalog, provider_key)
        if not provider_models:
            return False

        providers = dict(_cache_providers(existing))
        providers[provider_key] = provider_models
        next_cache = _new_cache(providers)
    else:
        next_cache = _build_cache(raw_catalog)
    if not _cache_has_models(next_cache):
        return False

    _write_cache(next_cache)
    _set_memory_cache(next_cache)
    return True


def _build_cache(
    raw_catalog: dict[str, Any],
) -> dict[str, Any]:
    providers: dict[str, dict[str, dict[str, Any]]] = {}

    for provider_id in LITELLM_PROVIDER_ALIASES:
        provider_models = _provider_models_from_catalog(raw_catalog, provider_id)
        if provider_models:
            providers[provider_id] = provider_models

    if not providers:
        return {}

    return _new_cache(providers)


def _new_cache(providers: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": MODEL_METADATA_CACHE_VERSION,
        "source": MODEL_METADATA_CACHE_SOURCE,
        "fetchedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "providers": providers,
    }


def _provider_models_from_catalog(
    raw_catalog: dict[str, Any],
    provider: str,
) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for source_key, value in raw_catalog.items():
        if source_key == "sample_spec" or not isinstance(value, dict):
            continue
        if not _catalog_item_belongs_to_provider(provider, str(source_key), value):
            continue

        model_id = _model_id_from_source_key(str(source_key))
        if not model_id:
            continue
        item = _lightweight_item_from_catalog_item(str(source_key), value)
        if item is not None:
            models[model_id] = item

    return dict(sorted(models.items(), key=lambda entry: entry[0].lower()))


def _catalog_item_belongs_to_provider(
    provider: str,
    source_key: str,
    value: dict[str, Any],
) -> bool:
    aliases = {
        _normalize_model_name(alias)
        for alias in LITELLM_PROVIDER_ALIASES.get(provider, set())
    }
    if not aliases:
        return False

    candidate_provider = _normalize_model_name(str(value.get("litellm_provider") or ""))
    source_prefix = _normalize_model_name(source_key.split("/", 1)[0])
    # Require LiteLLM's provider identity to match this ResuMate provider. This
    # keeps proxy-hosted variants such as OpenRouter, Azure, or Fireworks from
    # polluting official provider metadata.
    if candidate_provider:
        return candidate_provider in aliases

    return source_prefix in aliases


def _model_id_from_source_key(source_key: str) -> str:
    return source_key.rsplit("/", 1)[-1].strip()


def _lightweight_item_from_catalog_item(
    source_key: str,
    value: dict[str, Any],
) -> dict[str, Any] | None:
    item: dict[str, Any] = {"sourceKey": source_key}
    _set_positive_int(item, "contextWindowTokens", value.get("max_input_tokens"))
    _set_positive_int(item, "maxOutputTokens", value.get("max_output_tokens"))
    _set_optional_bool(item, "supportsImage", value.get("supports_vision"))
    _set_optional_bool(item, "supportsThinking", value.get("supports_reasoning"))
    _set_optional_bool(item, "supportsStreaming", value.get("supports_streaming"))

    supports_tools = _optional_bool(value.get("supports_function_calling"))
    if supports_tools is None:
        supports_tools = _optional_bool(value.get("supports_tool_choice"))
    if supports_tools is not None:
        item["supportsTools"] = supports_tools

    return item if len(item) > 1 else None


def _metadata_from_lightweight_item(value: dict[str, Any]) -> ModelMetadata | None:
    metadata = ModelMetadata(
        context_window_tokens=_positive_int(value.get("contextWindowTokens")),
        max_output_tokens=_positive_int(value.get("maxOutputTokens")),
        supports_image=_optional_bool(value.get("supportsImage")),
        supports_thinking=_optional_bool(value.get("supportsThinking")),
        supports_tools=_optional_bool(value.get("supportsTools")),
        supports_streaming=_optional_bool(value.get("supportsStreaming")),
    )
    if any(
        field is not None
        for field in (
            metadata.context_window_tokens,
            metadata.max_output_tokens,
            metadata.supports_image,
            metadata.supports_thinking,
            metadata.supports_tools,
            metadata.supports_streaming,
        )
    ):
        return metadata

    return None


def _load_cache() -> dict[str, Any]:
    global _CATALOG_CACHE

    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE

    cache = _read_cache(_cache_path())
    _CATALOG_CACHE = cache
    return cache


def _set_memory_cache(cache: dict[str, Any]) -> None:
    global _CATALOG_CACHE
    _CATALOG_CACHE = cache


def _cache_path() -> Path:
    return get_settings().data_dir / MODEL_METADATA_CACHE_NAME


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}
    if data.get("version") != MODEL_METADATA_CACHE_VERSION:
        return {}
    if not isinstance(data.get("providers"), dict):
        return {}

    return data


def _write_cache(cache: dict[str, Any]) -> None:
    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp_path.replace(cache_path)


def _cache_is_fresh(path: Path) -> bool:
    try:
        age_seconds = time.time() - path.stat().st_mtime
    except OSError:
        return False

    return age_seconds < MODEL_METADATA_CACHE_TTL_SECONDS


def _cache_providers(cache: dict[str, Any]) -> dict[str, Any]:
    providers = cache.get("providers")
    return providers if isinstance(providers, dict) else {}


def _cache_provider_models(cache: dict[str, Any], provider: str) -> dict[str, Any]:
    models = _cache_providers(cache).get(provider)
    return models if isinstance(models, dict) else {}


def _cache_has_models(cache: dict[str, Any]) -> bool:
    return any(
        isinstance(models, dict) and bool(models)
        for models in _cache_providers(cache).values()
    )


def _fetch_catalog() -> dict[str, Any]:
    request = urllib.request.Request(
        MODEL_METADATA_URL,
        headers={"User-Agent": "ResuMate/0.1 model metadata"},
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=MODEL_METADATA_FETCH_TIMEOUT_SECONDS,
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def _normalize_model_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _set_positive_int(item: dict[str, Any], key: str, value: Any) -> None:
    normalized = _positive_int(value)
    if normalized is not None:
        item[key] = normalized


def _set_optional_bool(item: dict[str, Any], key: str, value: Any) -> None:
    normalized = _optional_bool(value)
    if normalized is not None:
        item[key] = normalized


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0 and value.is_integer():
        return int(value)
    return None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
