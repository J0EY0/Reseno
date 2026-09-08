import asyncio
import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Any

import httpx

from app.config import get_settings
from app.services.model_context_reference import (
    ModelContextReference,
    normalize_base_context_models,
    normalize_ollama_context_models,
    resolve_context_reference,
    valid_context_models,
)

MODEL_METADATA_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
MODEL_REASONING_METADATA_URL = "https://models.dev/catalog.json"
MODEL_METADATA_CACHE_NAME = "model-metadata/model_capabilities.json"
MODEL_METADATA_FETCH_TIMEOUT_SECONDS = 15
MODEL_METADATA_REFRESH_INTERVAL_SECONDS = 60 * 60
MODEL_METADATA_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MODEL_METADATA_SNAPSHOT_PATH = Path(__file__).with_name("model_metadata_snapshot.json")
MODEL_METADATA_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
MODEL_METADATA_CACHE_VERSION = 6
MODEL_METADATA_CACHE_SOURCE = "litellm:model_prices_and_context_window+models.dev"

LITELLM_PROVIDER_ALIASES: dict[str, set[str]] = {
    "openai": {"openai"},
    "anthropic": {"anthropic"},
    "google": {"gemini"},
    "deepseek": {"deepseek"},
    "qwen": {"dashscope", "qwen"},
    "minimax": {"minimax"},
    "glm": {"bigmodel", "zhipu", "zhipuai", "zai"},
    "moonshot": {"moonshot"},
    "xai": {"xai"},
}

MODELS_DEV_PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "openai": ("openai",),
    "anthropic": ("anthropic",),
    "google": ("google",),
    "deepseek": ("deepseek",),
    "qwen": ("alibaba-cn",),
    "minimax": ("minimax-cn",),
    "glm": ("zhipuai",),
    "moonshot": ("moonshotai",),
    "xai": ("xai",),
}

_CATALOG_CACHE: dict[str, Any] | None = None
_CATALOG_CACHE_LOCK = RLock()
_REFRESH_LOCK = Lock()
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelMetadata:
    """Source-neutral model facts consumed by discovery and runtime limits."""

    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    shared_context_window_tokens: int | None = None
    supports_image: bool | None = None
    supports_thinking: bool | None = None
    can_disable_thinking: bool | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    supports_web_search: bool | None = None


def is_provider_model(provider: str, model: str) -> bool:
    """Return whether a model belongs in the provider's model catalog."""

    return provider.strip().casefold() != "qwen" or model.strip().casefold().startswith(
        ("qwen", "qwq", "qvq"),
    )


def resolve_model_metadata(provider: str, model: str) -> ModelMetadata | None:
    """Return cached normalized metadata for one provider/model pair."""

    return resolve_models_metadata(provider, [model]).get(model)


def resolve_model_context_reference(provider: str, model: str) -> ModelContextReference:
    """Read a model's reference context limit without querying its deployment."""

    cache = _load_cache()
    return resolve_context_reference(
        provider,
        model,
        _cache_catalog(cache, "modelsDev").get("contextModels", {}),
        _cache_catalog(cache, "litellm").get("contextModels", {}),
    )


def resolve_models_metadata(
    provider: str,
    models: list[str],
) -> dict[str, ModelMetadata]:
    """Resolve selected model ids against one current provider catalog snapshot."""

    provider_key = provider.strip().lower()
    model_keys = {
        model: _normalize_model_name(model)
        for model in models
        if model.strip() and is_provider_model(provider_key, model)
    }
    if not provider_key or not model_keys:
        return {}

    cache = _load_cache()
    provider_models = _cache_provider_models(cache, provider_key)
    normalized_models: dict[str, dict[str, Any]] = {}
    for cached_model, value in provider_models.items():
        if isinstance(value, dict):
            normalized_models.setdefault(_normalize_model_name(cached_model), value)

    result: dict[str, ModelMetadata] = {}
    for model, normalized_model in model_keys.items():
        value = normalized_models.get(normalized_model)
        if value is not None:
            metadata = _metadata_from_lightweight_item(value)
            if metadata is not None:
                result[model] = metadata
    return result


@asynccontextmanager
async def model_metadata_lifespan() -> AsyncIterator[None]:
    """Load local model facts and refresh expired sources in the background."""

    _load_cache()
    task = asyncio.create_task(_refresh_loop(), name="model-metadata-refresh")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _refresh_loop() -> None:
    while True:
        await refresh_model_metadata_cache()
        await asyncio.sleep(MODEL_METADATA_REFRESH_INTERVAL_SECONDS)


async def refresh_model_metadata_cache() -> bool:
    """Refresh expired sources once, retaining usable facts on failure."""

    if not _REFRESH_LOCK.acquire(blocking=False):
        return False
    try:
        cached = _load_cache()
        sources = [
            source
            for source in ("litellm", "modelsDev")
            if not _cache_catalog_is_fresh(cached, source)
        ]
        updates = await asyncio.gather(
            *(_refresh_catalog(source) for source in sources)
        )
        if not any(updates):
            return False
        with _CATALOG_CACHE_LOCK:
            current = _load_cache()
            catalogs = {
                source: _cache_catalog(current, source)
                for source in ("litellm", "modelsDev")
            }
            for source, update in zip(sources, updates, strict=True):
                if update is not None:
                    catalogs[source] = update
            next_cache = _new_cache(
                catalogs["litellm"].get("providers", {}),
                catalogs["litellm"].get("fetchedAt"),
                catalogs["modelsDev"].get("providers", {}),
                catalogs["modelsDev"].get("fetchedAt"),
                litellm_context_models=catalogs["litellm"].get("contextModels", {}),
                base_context_models=catalogs["modelsDev"].get("contextModels", {}),
            )
            try:
                _write_cache(next_cache)
            except OSError:
                _LOGGER.warning("Model metadata cache could not be persisted.")
            _set_memory_cache(next_cache)
        return True
    finally:
        _REFRESH_LOCK.release()


async def _refresh_catalog(source: str) -> dict[str, Any] | None:
    raw = await (
        _fetch_catalog() if source == "litellm" else _fetch_reasoning_catalog()
    )
    try:
        return _build_catalog(source, raw, datetime.now(UTC).isoformat())
    except ValueError:
        return None


def build_model_metadata_snapshot(
    litellm: dict[str, Any],
    reasoning: dict[str, Any],
    *,
    fetched_at: str,
) -> dict[str, Any]:
    """Normalize both upstream catalogs into the distributable model snapshot."""

    if _parse_fetched_at(fetched_at) is None:
        raise ValueError("Model metadata snapshot timestamp is invalid.")
    return {
        "version": MODEL_METADATA_CACHE_VERSION,
        "source": MODEL_METADATA_CACHE_SOURCE,
        "catalogs": {
            "litellm": _build_catalog("litellm", litellm, fetched_at),
            "modelsDev": _build_catalog("modelsDev", reasoning, fetched_at),
        },
    }


def _build_catalog(source: str, raw: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    providers = _normalize_catalog(source, raw)
    context_models = (
        normalize_ollama_context_models(raw)
        if source == "litellm"
        else normalize_base_context_models(raw.get("models"))
    )
    return {
        "fetchedAt": fetched_at,
        "providers": providers,
        "contextModels": context_models,
    }


def _normalize_catalog(source: str, raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Model metadata catalog must be an object.")
    if source == "litellm":
        providers = _litellm_providers_from_catalog(raw)
    else:
        raw_providers = raw.get("providers")
        if not isinstance(raw_providers, dict):
            raise ValueError("Model metadata providers must be an object.")
        providers = _reasoning_providers_from_catalog(raw_providers)
    if not _valid_providers(providers):
        raise ValueError("Model metadata catalog contains no usable model facts.")
    return providers


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
    *,
    litellm_context_models: dict[str, Any] | None = None,
    base_context_models: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one cache while retaining independent source refresh state."""

    return {
        "version": MODEL_METADATA_CACHE_VERSION,
        "source": MODEL_METADATA_CACHE_SOURCE,
        "catalogs": {
            "litellm": {
                "fetchedAt": litellm_fetched_at,
                "providers": litellm_providers,
                "contextModels": litellm_context_models or {},
            },
            "modelsDev": {
                "fetchedAt": reasoning_fetched_at,
                "providers": reasoning_providers,
                "contextModels": base_context_models or {},
            },
        },
    }


def _provider_models_from_catalog(
    raw_catalog: dict[str, Any],
    provider: str,
) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for source_key in sorted(
        raw_catalog,
        key=lambda key: (
            _model_id_from_source_key(str(key), provider) != str(key).strip(),
            str(key),
        ),
    ):
        value = raw_catalog[source_key]
        if source_key == "sample_spec" or not isinstance(value, dict):
            continue
        if not _catalog_item_belongs_to_provider(provider, str(source_key), value):
            continue

        model_id = _model_id_from_source_key(str(source_key), provider)
        if not model_id or not is_provider_model(provider, model_id):
            continue
        item = _lightweight_item_from_catalog_item(str(source_key), value)
        if item is not None:
            if provider == "anthropic":
                _set_positive_int(
                    item, "sharedContextWindowTokens", value.get("max_input_tokens"),
                )
            models.setdefault(model_id, item)

    return dict(sorted(models.items(), key=lambda entry: entry[0].lower()))


def _provider_models_from_reasoning_catalog(
    raw_catalog: dict[str, Any],
    provider: str,
) -> dict[str, dict[str, Any]]:
    """Extract explicit limits and Off controls from one provider catalog."""

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
            raw_model_id = value.get("id")
            model_id = (
                raw_model_id if isinstance(raw_model_id, str) else str(source_key)
            ).strip()
            if not model_id or not is_provider_model(provider, model_id):
                continue
            item: dict[str, Any] = {
                "sourceKey": f"models.dev:{source_provider}/{source_key}",
            }
            limits = value.get("limit")
            if isinstance(limits, dict) and provider != "google":
                _set_positive_int(
                    item, "sharedContextWindowTokens", limits.get("context"),
                )
            _set_optional_bool(item, "canDisableThinking", can_disable)
            if len(item) == 1:
                continue
            supports_thinking = _optional_bool(value.get("reasoning"))
            if can_disable is not None and supports_thinking is not None:
                item["supportsThinking"] = supports_thinking
            models[model_id] = item

    return models


def _merge_reasoning_metadata(
    provider_models: dict[str, dict[str, Any]],
    reasoning_models: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Add models.dev limits and Off facts without replacing LiteLLM facts."""

    merged = {model_id: dict(value) for model_id, value in provider_models.items()}
    normalized_ids = {_normalize_model_name(model_id): model_id for model_id in merged}
    for model_id, reasoning in reasoning_models.items():
        target_id = normalized_ids.get(_normalize_model_name(model_id), model_id)
        existing = merged.get(target_id, {})
        merged[target_id] = {**reasoning, **existing}
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
    # Require LiteLLM's provider identity to match this Reseno provider. This
    # keeps proxy-hosted variants such as OpenRouter, Azure, or Fireworks from
    # polluting official provider metadata.
    if candidate_provider:
        return candidate_provider in aliases

    return source_prefix in aliases


def _model_id_from_source_key(source_key: str, provider: str) -> str:
    prefix, separator, model = source_key.strip().partition("/")
    if separator and prefix.casefold() in LITELLM_PROVIDER_ALIASES.get(provider, set()):
        return model.strip()
    return source_key.strip()


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
    _set_optional_bool(
        item, "supportsStreaming", value.get("supports_native_streaming")
    )
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
        shared_context_window_tokens=_positive_int(value.get("sharedContextWindowTokens")),
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
            metadata.shared_context_window_tokens,
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

    with _CATALOG_CACHE_LOCK:
        if _CATALOG_CACHE is None:
            bundled = _read_cache(MODEL_METADATA_SNAPSHOT_PATH)
            persisted = _read_cache(_cache_path())
            catalogs = {}
            for source in ("litellm", "modelsDev"):
                candidates = [
                    _cache_catalog(snapshot, source)
                    for snapshot in (persisted, bundled)
                ]
                catalogs[source] = max(
                    candidates,
                    key=lambda catalog: (
                        _parse_fetched_at(catalog.get("fetchedAt"))
                        or datetime.min.replace(tzinfo=UTC)
                    ),
                )
            _CATALOG_CACHE = _new_cache(
                catalogs["litellm"].get("providers", {}),
                catalogs["litellm"].get("fetchedAt"),
                catalogs["modelsDev"].get("providers", {}),
                catalogs["modelsDev"].get("fetchedAt"),
                litellm_context_models=catalogs["litellm"].get("contextModels", {}),
                base_context_models=catalogs["modelsDev"].get("contextModels", {}),
            )
        return _CATALOG_CACHE


def _set_memory_cache(cache: dict[str, Any]) -> None:
    global _CATALOG_CACHE
    with _CATALOG_CACHE_LOCK:
        _CATALOG_CACHE = cache


def _cache_path() -> Path:
    return get_settings().data_dir / MODEL_METADATA_CACHE_NAME


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(data, dict)
        or data.get("version") != MODEL_METADATA_CACHE_VERSION
    ):
        return {}
    catalogs = data.get("catalogs")
    if not isinstance(catalogs, dict):
        return {}
    valid = {}
    for source in ("litellm", "modelsDev"):
        catalog = catalogs.get(source)
        if (
            isinstance(catalog, dict)
            and _parse_fetched_at(catalog.get("fetchedAt")) is not None
            and _valid_providers(catalog.get("providers"))
            and valid_context_models(catalog.get("contextModels"))
        ):
            valid[source] = catalog
    return {"catalogs": valid}


def _valid_providers(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    has_models = False
    numeric = {"contextWindowTokens", "maxOutputTokens", "sharedContextWindowTokens"}
    boolean = {
        "supportsImage",
        "supportsThinking",
        "canDisableThinking",
        "supportsTools",
        "supportsStreaming",
        "supportsWebSearch",
    }
    for provider, models in value.items():
        if provider not in LITELLM_PROVIDER_ALIASES or not isinstance(models, dict):
            return False
        for model, item in models.items():
            if (
                not isinstance(model, str)
                or not model.strip()
                or not isinstance(item, dict)
            ):
                return False
            if not item.keys() & (numeric | boolean):
                return False
            for key, field in item.items():
                if key in numeric:
                    if type(field) is not int or field <= 0:
                        return False
                elif key in boolean:
                    if not isinstance(field, bool):
                        return False
                elif key != "sourceKey" or not isinstance(field, str):
                    return False
            has_models = True
    return has_models


def _parse_fetched_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        fetched = datetime.fromisoformat(value)
    except ValueError:
        return None
    if fetched.tzinfo is None or fetched > datetime.now(UTC):
        return None
    return fetched


def _write_cache(cache: dict[str, Any]) -> None:
    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=cache_path.parent,
        prefix=f".{cache_path.name}.",
        suffix=".tmp",
        text=True,
    )
    tmp_path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temp_file:
            json.dump(cache, temp_file, ensure_ascii=False, separators=(",", ":"))
        tmp_path.replace(cache_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _cache_sources_are_fresh(cache: dict[str, Any]) -> bool:
    """Return whether both independent supplemental sources are fresh."""

    return all(
        _cache_catalog_is_fresh(cache, source) for source in ("litellm", "modelsDev")
    )


def _cache_catalog_is_fresh(cache: dict[str, Any], source: str) -> bool:
    fetched = _parse_fetched_at(_cache_catalog_fetched_at(cache, source))
    if fetched is None or not _cache_catalog_providers(cache, source):
        return False
    return (
        datetime.now(UTC) - fetched
    ).total_seconds() < MODEL_METADATA_CACHE_TTL_SECONDS


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
    return _merge_reasoning_metadata(
        normalized_litellm_models,
        normalized_reasoning_models,
    )


async def _fetch_catalog() -> dict[str, Any]:
    return await _fetch_json(MODEL_METADATA_URL)


async def _fetch_reasoning_catalog() -> dict[str, Any]:
    return await _fetch_json(MODEL_REASONING_METADATA_URL)


async def _fetch_json(url: str) -> dict[str, Any]:
    try:
        async with asyncio.timeout(MODEL_METADATA_FETCH_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                timeout=MODEL_METADATA_FETCH_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": "Reseno/0.1 model metadata"},
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > MODEL_METADATA_MAX_DOWNLOAD_BYTES:
                            return {}
                data = json.loads(payload)
    except (httpx.HTTPError, ImportError, OSError, TimeoutError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_model_name(value: str) -> str:
    return value.strip().casefold()


def _set_positive_int(item: dict[str, Any], key: str, value: Any) -> None:
    normalized = _positive_int(value)
    if normalized is not None:
        item[key] = normalized


def _set_optional_bool(item: dict[str, Any], key: str, value: Any) -> None:
    normalized = _optional_bool(value)
    if normalized is not None:
        item[key] = normalized


def _positive_int(value: Any) -> int | None:
    if type(value) is int and value > 0:
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

    if value.get("thinking_always_on") is True:
        return False

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
        "reasoning_effort_levels",
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
