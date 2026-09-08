from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.config import get_settings
from app.services.model_metadata import (
    MODEL_METADATA_CACHE_TTL_SECONDS,
    is_provider_model,
)
from app.services.model_providers import DiscoveredModel
from app.services.thinking import ThinkingControl, available_thinking_modes

MODEL_DISCOVERY_CACHE_NAME = "model-discovery-cache"
MODEL_DISCOVERY_CACHE_VERSION = 5


def read_cached_provider_models(provider_id: str) -> list[DiscoveredModel] | None:
    """Return cached normalized discovery results for one provider."""

    entry = _read_cache(provider_id)
    if not isinstance(entry, dict):
        return None

    raw_models = entry.get("models")
    if not isinstance(raw_models, list):
        return None

    allow_thinking_off = _cache_is_fresh(entry)
    models = [
        _model_from_cache_item(
            item,
            allow_thinking_off=allow_thinking_off,
        )
        for item in raw_models
    ]
    filtered = [
        model
        for model in models
        if model is not None and is_provider_model(provider_id, model.id)
    ]
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

    cache = {
        "version": MODEL_DISCOVERY_CACHE_VERSION,
        "provider": provider_id,
        "fetchedAt": datetime.now(UTC).isoformat(),
        "models": [_model_to_cache_item(model) for model in models],
    }
    _write_cache(provider_id, cache)


def _cache_path(provider_id: str) -> Path:
    return get_settings().data_dir / MODEL_DISCOVERY_CACHE_NAME / f"{provider_id}.json"


def _read_cache(provider_id: str) -> dict[str, Any] | None:
    path = _cache_path(provider_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("version") != MODEL_DISCOVERY_CACHE_VERSION:
        return None
    if payload.get("provider") != provider_id:
        return None

    return payload


def _write_cache(provider_id: str, cache: dict[str, Any]) -> None:
    path = _cache_path(provider_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
            json.dump(
                cache,
                temp_file,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _model_to_cache_item(model: DiscoveredModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "label": model.label,
        "contextWindowTokens": model.context_window_tokens,
        "maxOutputTokens": model.max_output_tokens,
        "sharedContextWindowTokens": model.shared_context_window_tokens,
        "supportsImage": model.supports_image,
        "thinkingControl": model.thinking_control,
        "availableThinkingModes": list(model.available_thinking_modes),
        "supportsTools": model.supports_tools,
        "supportsStreaming": model.supports_streaming,
        "metadataSource": model.metadata_source,
    }


def _model_from_cache_item(
    item: object,
    *,
    allow_thinking_off: bool,
) -> DiscoveredModel | None:
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

    shared_context = item.get("sharedContextWindowTokens")
    if type(shared_context) is not int or shared_context <= 0:
        shared_context = None

    metadata_source = item.get("metadataSource")
    if not isinstance(metadata_source, str) or not metadata_source.strip():
        metadata_source = "cache"

    return DiscoveredModel(
        id=model_id,
        label=label,
        context_window_tokens=context_window,
        max_output_tokens=max_output,
        shared_context_window_tokens=shared_context,
        supports_image=bool(item.get("supportsImage")),
        thinking_control=_thinking_control(item.get("thinkingControl")),
        metadata_source=metadata_source,
        available_thinking_modes=available_thinking_modes(
            allow_thinking_off
            and _cache_allows_thinking_off(item.get("availableThinkingModes")),
        ),
        supports_tools=_optional_bool(item.get("supportsTools"), default=True),
        supports_streaming=_optional_bool(item.get("supportsStreaming"), default=True),
    )


def _optional_bool(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _thinking_control(value: object) -> ThinkingControl:
    if value in {"provider_default", "native_auto", "native_budget"}:
        return cast(ThinkingControl, value)
    return "none"


def _cache_allows_thinking_off(value: object) -> bool:
    """Read only the canonical Off member from a versioned cache record."""

    return isinstance(value, list) and "off" in value


def _cache_is_fresh(entry: dict[str, Any]) -> bool:
    """Return whether cached Off evidence is still within its trust window."""

    fetched_at = entry.get("fetchedAt")
    if not isinstance(fetched_at, str):
        return False
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    age_seconds = (datetime.now(UTC) - fetched).total_seconds()
    return 0 <= age_seconds < MODEL_METADATA_CACHE_TTL_SECONDS
