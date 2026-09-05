import json
import re
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
MODEL_REASONING_METADATA_URL = "https://models.dev/api.json"
MODEL_METADATA_CACHE_NAME = "model-metadata/model_capabilities.json"
MODEL_METADATA_FETCH_TIMEOUT_SECONDS = 1.5
MODEL_METADATA_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MODEL_METADATA_CACHE_VERSION = 3
MODEL_METADATA_CACHE_SOURCE = "litellm:model_prices_and_context_window+models.dev"

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

# models.dev provider ids are normalized here so its reasoning controls can
# enrich the same ResuMate provider/model seam used by discovery. This source
# supplies only explicit Off capability; token limits and other runtime facts
# continue to come from provider responses and LiteLLM.
MODELS_DEV_PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "openai": ("openai",),
    "anthropic": ("anthropic",),
    "google": ("google",),
    "deepseek": ("deepseek",),
    "qwen": ("alibaba",),
    "minimax": ("minimax",),
    "glm": ("zai",),
    "moonshot": ("moonshotai",),
    "xai": ("xai",),
}

_CATALOG_CACHE: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelMetadata:
    """Source-neutral model facts consumed by discovery and runtime limits."""

    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    supports_image: bool | None = None
    supports_thinking: bool | None = None
    can_disable_thinking: bool | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    supports_web_search: bool | None = None


def resolve_model_metadata(provider: str, model: str) -> ModelMetadata | None:
    """Return cached normalized metadata for one provider/model pair."""

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
    """Ensure the lightweight provider metadata cache exists when possible."""

    cache_path = _cache_path()
    cached = _read_cache(cache_path) if cache_path.exists() else {}
    if cached and _cache_sources_are_fresh(cached):
        _set_memory_cache(cached)
        return True

    return refresh_model_metadata_cache() or bool(cached)


def ensure_provider_model_metadata(provider: str, model_ids: list[str]) -> bool:
    """Refresh one provider's lightweight metadata when current cache misses models.

    Provider discovery must not fail because either supplemental catalog is
    unavailable. This helper therefore returns a best-effort boolean and never
    raises for refresh failures; callers still return provider-discovered models.
    """

    provider_key = provider.strip().lower()
    normalized_targets = {
        _normalize_model_name(model_id) for model_id in model_ids if model_id.strip()
    }
    if not provider_key or not normalized_targets:
        return False

    cache = _load_cache()
    provider_models = _cache_provider_models(cache, provider_key)
    cached_names = {_normalize_model_name(model_id) for model_id in provider_models}
    has_miss = not normalized_targets.issubset(cached_names)
    if provider_models and not has_miss and _cache_sources_are_fresh(cache):
        return True

    return refresh_model_metadata_cache(provider=provider_key)


def refresh_model_metadata_cache(provider: str | None = None) -> bool:
    """Fetch supplemental catalogs and persist ResuMate's lightweight subset."""

    raw_catalog = _fetch_catalog()
    reasoning_catalog = _fetch_reasoning_catalog()
    if not raw_catalog and not reasoning_catalog:
        return False

    provider_key = provider.strip().lower() if provider else None
    existing = _load_cache()
    litellm_providers = dict(_cache_catalog_providers(existing, "litellm"))
    reasoning_providers = dict(_cache_catalog_providers(existing, "modelsDev"))
    litellm_fetched_at = _cache_catalog_fetched_at(existing, "litellm")
    reasoning_fetched_at = _cache_catalog_fetched_at(existing, "modelsDev")
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    if provider_key:
        updated = False
        litellm_models = _provider_models_from_catalog(raw_catalog, provider_key)
        if litellm_models:
            # Each HTTP response is a complete source catalog. Once it proves
            # the requested provider is present, replace that source wholesale
            # so the single source timestamp describes every stored provider.
            litellm_providers = _litellm_providers_from_catalog(raw_catalog)
            litellm_fetched_at = fetched_at
            updated = True

        if _reasoning_catalog_has_provider(reasoning_catalog, provider_key):
            reasoning_providers = _reasoning_providers_from_catalog(
                reasoning_catalog,
            )
            reasoning_fetched_at = fetched_at
            updated = True

        if not updated:
            return False

        next_cache = _new_cache(
            litellm_providers,
            litellm_fetched_at,
            reasoning_providers,
            reasoning_fetched_at,
        )
    else:
        if raw_catalog:
            litellm_providers = _litellm_providers_from_catalog(raw_catalog)
            litellm_fetched_at = fetched_at
        if reasoning_catalog:
            reasoning_providers = _reasoning_providers_from_catalog(
                reasoning_catalog,
            )
            reasoning_fetched_at = fetched_at
        next_cache = _new_cache(
            litellm_providers,
            litellm_fetched_at,
            reasoning_providers,
            reasoning_fetched_at,
        )
    if not _cache_has_models(next_cache):
        return False

    _write_cache(next_cache)
    _set_memory_cache(next_cache)
    return True


def _build_cache(
    raw_catalog: dict[str, Any],
    reasoning_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    return _new_cache(
        _litellm_providers_from_catalog(raw_catalog),
        fetched_at if raw_catalog else None,
        _reasoning_providers_from_catalog(reasoning_catalog or {}),
        fetched_at if reasoning_catalog else None,
    )


def _litellm_providers_from_catalog(
    raw_catalog: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    providers: dict[str, dict[str, dict[str, Any]]] = {}

    for provider_id in LITELLM_PROVIDER_ALIASES:
        provider_models = _provider_models_from_catalog(raw_catalog, provider_id)
        if provider_models:
            providers[provider_id] = provider_models

    return providers


def _reasoning_providers_from_catalog(
    raw_catalog: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    providers: dict[str, dict[str, dict[str, Any]]] = {}

    for provider_id in MODELS_DEV_PROVIDER_ALIASES:
        provider_models = _provider_models_from_reasoning_catalog(
            raw_catalog,
            provider_id,
        )
        if provider_models:
            providers[provider_id] = provider_models

    return providers


def _new_cache(
    litellm_providers: dict[str, Any],
    litellm_fetched_at: str | None,
    reasoning_providers: dict[str, Any],
    reasoning_fetched_at: str | None,
) -> dict[str, Any]:
    """Build one cache while retaining independent source refresh state."""

    return {
        "version": MODEL_METADATA_CACHE_VERSION,
        "source": MODEL_METADATA_CACHE_SOURCE,
        "catalogs": {
            "litellm": {
                "fetchedAt": litellm_fetched_at,
                "providers": litellm_providers,
            },
            "modelsDev": {
                "fetchedAt": reasoning_fetched_at,
                "providers": reasoning_providers,
            },
        },
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


def _provider_models_from_reasoning_catalog(
    raw_catalog: dict[str, Any],
    provider: str,
) -> dict[str, dict[str, Any]]:
    """Extract only explicit Off controls from one models.dev provider entry."""

    models: dict[str, dict[str, Any]] = {}
    for source_provider in MODELS_DEV_PROVIDER_ALIASES.get(provider, ()):
        provider_entry = raw_catalog.get(source_provider)
        if not isinstance(provider_entry, dict):
            continue
        raw_models = provider_entry.get("models")
        if not isinstance(raw_models, dict):
            continue

        for source_key, value in raw_models.items():
            if not isinstance(value, dict):
                continue
            can_disable = explicit_thinking_off_capability(value)
            if can_disable is None:
                continue
            raw_model_id = value.get("id")
            model_id = _model_id_from_source_key(
                raw_model_id if isinstance(raw_model_id, str) else str(source_key),
            )
            if not model_id:
                continue
            item: dict[str, Any] = {
                "sourceKey": f"models.dev:{source_provider}/{source_key}",
                "canDisableThinking": can_disable,
            }
            supports_thinking = _optional_bool(value.get("reasoning"))
            if supports_thinking is not None:
                item["supportsThinking"] = supports_thinking
            models[model_id] = item

    return models


def _reasoning_catalog_has_provider(
    raw_catalog: dict[str, Any],
    provider: str,
) -> bool:
    """Return whether a fetched models.dev catalog covers this provider."""

    return any(
        isinstance(raw_catalog.get(source_provider), dict)
        for source_provider in MODELS_DEV_PROVIDER_ALIASES.get(provider, ())
    )


def _merge_reasoning_metadata(
    provider_models: dict[str, dict[str, Any]],
    reasoning_models: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge models.dev Off facts without replacing LiteLLM capabilities."""

    merged = {model_id: dict(value) for model_id, value in provider_models.items()}
    normalized_ids = {_normalize_model_name(model_id): model_id for model_id in merged}
    for model_id, reasoning in reasoning_models.items():
        target_id = normalized_ids.get(_normalize_model_name(model_id), model_id)
        existing = merged.get(target_id, {})
        merged[target_id] = {**reasoning, **existing}
        if "canDisableThinking" in reasoning:
            merged[target_id]["canDisableThinking"] = reasoning["canDisableThinking"]
    return dict(sorted(merged.items(), key=lambda entry: entry[0].lower()))


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
    _set_optional_bool(
        item,
        "canDisableThinking",
        explicit_thinking_off_capability(value),
    )
    _set_optional_bool(item, "supportsStreaming", value.get("supports_streaming"))
    _set_optional_bool(item, "supportsWebSearch", value.get("supports_web_search"))

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
        can_disable_thinking=_optional_bool(value.get("canDisableThinking")),
        supports_tools=_optional_bool(value.get("supportsTools")),
        supports_streaming=_optional_bool(value.get("supportsStreaming")),
        supports_web_search=_optional_bool(value.get("supportsWebSearch")),
    )
    if any(
        field is not None
        for field in (
            metadata.context_window_tokens,
            metadata.max_output_tokens,
            metadata.supports_image,
            metadata.supports_thinking,
            metadata.can_disable_thinking,
            metadata.supports_tools,
            metadata.supports_streaming,
            metadata.supports_web_search,
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
    catalogs = data.get("catalogs")
    if not isinstance(catalogs, dict):
        return {}
    if not isinstance(catalogs.get("litellm"), dict):
        return {}
    if not isinstance(catalogs.get("modelsDev"), dict):
        return {}
    for source in ("litellm", "modelsDev"):
        catalog = catalogs[source]
        if not isinstance(catalog.get("providers"), dict):
            return {}
        if not isinstance(catalog.get("fetchedAt"), (str, type(None))):
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


def _cache_sources_are_fresh(cache: dict[str, Any]) -> bool:
    """Return whether both independent supplemental sources are fresh."""

    return all(
        _cache_catalog_is_fresh(cache, source) for source in ("litellm", "modelsDev")
    )


def _cache_catalog_is_fresh(cache: dict[str, Any], source: str) -> bool:
    fetched_at = _cache_catalog_fetched_at(cache, source)
    if fetched_at is None:
        return False
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    age_seconds = (datetime.now(UTC) - fetched).total_seconds()
    return 0 <= age_seconds < MODEL_METADATA_CACHE_TTL_SECONDS


def _cache_catalog(cache: dict[str, Any], source: str) -> dict[str, Any]:
    catalogs = cache.get("catalogs")
    if not isinstance(catalogs, dict):
        return {}
    catalog = catalogs.get(source)
    return catalog if isinstance(catalog, dict) else {}


def _cache_catalog_providers(
    cache: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    providers = _cache_catalog(cache, source).get("providers")
    return providers if isinstance(providers, dict) else {}


def _cache_catalog_fetched_at(
    cache: dict[str, Any],
    source: str,
) -> str | None:
    fetched_at = _cache_catalog(cache, source).get("fetchedAt")
    return fetched_at if isinstance(fetched_at, str) else None


def _cache_provider_models(cache: dict[str, Any], provider: str) -> dict[str, Any]:
    litellm_models = _cache_catalog_providers(cache, "litellm").get(provider)
    reasoning_models = _cache_catalog_providers(cache, "modelsDev").get(provider)
    normalized_litellm_models = (
        litellm_models if isinstance(litellm_models, dict) else {}
    )
    normalized_reasoning_models = (
        reasoning_models if isinstance(reasoning_models, dict) else {}
    )
    # Token ceilings remain useful conservative fallbacks when a catalog is
    # stale. Off is different: advertising a removed disable control can make
    # an accepted user preference execute as reasoning-enabled. Strip only that
    # capability until the owning source refreshes successfully.
    if not _cache_catalog_is_fresh(cache, "litellm"):
        normalized_litellm_models = _without_disable_capability(
            normalized_litellm_models,
        )
    if not _cache_catalog_is_fresh(cache, "modelsDev"):
        normalized_reasoning_models = _without_disable_capability(
            normalized_reasoning_models,
        )
    return _merge_reasoning_metadata(
        normalized_litellm_models,
        normalized_reasoning_models,
    )


def _without_disable_capability(
    provider_models: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Copy cached models while removing a stale Off declaration."""

    result: dict[str, dict[str, Any]] = {}
    for model_id, value in provider_models.items():
        if not isinstance(value, dict):
            continue
        item = dict(value)
        item.pop("canDisableThinking", None)
        result[model_id] = item
    return result


def _cache_has_models(cache: dict[str, Any]) -> bool:
    return any(
        isinstance(models, dict) and bool(models)
        for source in ("litellm", "modelsDev")
        for models in _cache_catalog_providers(cache, source).values()
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


def _fetch_reasoning_catalog() -> dict[str, Any]:
    """Fetch the optional models.dev catalog used for reasoning controls."""

    request = urllib.request.Request(
        MODEL_REASONING_METADATA_URL,
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


def explicit_thinking_off_capability(value: dict[str, Any]) -> bool | None:
    """Read an explicit reasoning-disable capability from provider metadata.

    The return value is tri-state: ``True`` and ``False`` are authoritative
    declarations, while ``None`` means the metadata contains no recognized
    statement. A generic reasoning-support flag is intentionally insufficient;
    it proves that a model may reason, not that reasoning can be disabled.

    Supported source shapes cover the normalized LiteLLM flag, provider/model
    effort lists, models.dev-style reasoning options, and Anthropic's nested
    thinking type capability.
    """

    for key in (
        "supports_none_reasoning_effort",
        "can_disable_thinking",
        "canDisableThinking",
    ):
        explicit = _optional_bool(value.get(key))
        if explicit is not None:
            return explicit

    disabled = _nested_optional_bool(
        value,
        "capabilities",
        "thinking",
        "types",
        "disabled",
        "supported",
    )
    if disabled is not None:
        return disabled

    for key in (
        "reasoning_options",
        "reasoningOptions",
        "supported_reasoning_efforts",
        "supportedReasoningEfforts",
    ):
        if key not in value:
            continue
        return _reasoning_options_allow_off(value[key])

    return None


def _reasoning_options_allow_off(value: Any) -> bool | None:
    """Return whether one explicit reasoning-options value includes Off."""

    if isinstance(value, str):
        return value.strip().casefold() == "none"
    if isinstance(value, list):
        return any(_reasoning_option_allows_off(option) for option in value)
    if isinstance(value, dict):
        return _reasoning_option_allows_off(value)
    return None


def _reasoning_option_allows_off(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() == "none"
    if not isinstance(value, dict):
        return False

    option_type = value.get("type")
    if isinstance(option_type, str) and option_type.casefold() == "toggle":
        return True

    for key in ("values", "efforts", "levels", "effort"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip().casefold() == "none":
            return True
        if isinstance(candidate, list) and any(
            isinstance(item, str) and item.strip().casefold() == "none"
            for item in candidate
        ):
            return True
    return False


def _nested_optional_bool(value: dict[str, Any], *path: str) -> bool | None:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _optional_bool(current)
