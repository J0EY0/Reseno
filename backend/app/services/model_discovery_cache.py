from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.model_providers import DiscoveredModel

MODEL_DISCOVERY_CACHE_NAME = "model-discovery-cache.json"
MODEL_DISCOVERY_CACHE_VERSION = 1


def read_cached_provider_models(provider_id: str) -> list[DiscoveredModel] | None:
    """Return cached normalized discovery results for one provider."""

    entry = _read_cache().get("providers", {}).get(provider_id)
    if not isinstance(entry, dict):
        return None

    raw_models = entry.get("models")
    if not isinstance(raw_models, list):
        return None

    models = [_model_from_cache_item(item) for item in raw_models]
    filtered = [model for model in models if model is not None]
    return filtered or None


def get_cached_provider_model(
    provider_id: str,
    model_id: str,
) -> DiscoveredModel | None:
    """Return one cached model by provider and model id."""

    models = read_cached_provider_models(provider_id)
    if models is None:
        return None

    return next((model for model in models if model.id == model_id), None)


def write_cached_provider_models(
    provider_id: str,
    models: list[DiscoveredModel],
) -> None:
    """Persist normalized discovery results for one provider."""

    cache = _read_cache()
    providers = cache.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        cache["providers"] = providers

    providers[provider_id] = {
        "provider": provider_id,
        "fetchedAt": datetime.now(UTC).isoformat(),
        "models": [_model_to_cache_item(model) for model in models],
    }
    _write_cache(cache)


def _cache_path() -> Path:
    return get_settings().data_dir / MODEL_DISCOVERY_CACHE_NAME


def _read_cache() -> dict[str, Any]:
    path = _cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"version": MODEL_DISCOVERY_CACHE_VERSION, "providers": {}}

    if not isinstance(payload, dict):
        return {"version": MODEL_DISCOVERY_CACHE_VERSION, "providers": {}}
    if payload.get("version") != MODEL_DISCOVERY_CACHE_VERSION:
        return {"version": MODEL_DISCOVERY_CACHE_VERSION, "providers": {}}
    if not isinstance(payload.get("providers"), dict):
        payload["providers"] = {}

    return payload


def _write_cache(cache: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _model_to_cache_item(model: DiscoveredModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "label": model.label,
        "contextWindowTokens": model.context_window_tokens,
        "maxOutputTokens": model.max_output_tokens,
        "supportsImage": model.supports_image,
        "supportsThinking": model.supports_thinking,
        "metadataSource": model.metadata_source,
    }


def _model_from_cache_item(item: object) -> DiscoveredModel | None:
    if not isinstance(item, dict):
        return None

    model_id = item.get("id")
    label = item.get("label")
    context_window = item.get("contextWindowTokens")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    if not isinstance(label, str) or not label.strip():
        label = model_id
    if not isinstance(context_window, int) or context_window <= 0:
        return None

    max_output = item.get("maxOutputTokens")
    if not isinstance(max_output, int) or max_output <= 0:
        max_output = None

    metadata_source = item.get("metadataSource")
    if not isinstance(metadata_source, str) or not metadata_source.strip():
        metadata_source = "cache"

    return DiscoveredModel(
        id=model_id,
        label=label,
        context_window_tokens=context_window,
        max_output_tokens=max_output,
        supports_image=bool(item.get("supportsImage")),
        supports_thinking=bool(item.get("supportsThinking")),
        metadata_source=metadata_source,
    )
