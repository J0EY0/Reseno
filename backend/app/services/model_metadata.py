import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings

MODEL_METADATA_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
MODEL_METADATA_CACHE_NAME = "model_prices_and_context_window.json"
MODEL_METADATA_FETCH_TIMEOUT_SECONDS = 1.5

_CATALOG_CACHE: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModelMetadata:
    """LiteLLM model metadata relevant to ResuMate runtime limits."""

    context_window_tokens: int | None
    max_output_tokens: int | None


def resolve_model_metadata(provider: str, model: str) -> ModelMetadata | None:
    """Return model token limits from the in-memory or local disk catalog."""

    provider_key = provider.strip().lower()
    model_key = model.strip().lower()
    if not model_key:
        return None

    catalog = _load_catalog(refresh=False)
    return _match_model_metadata(catalog, provider_key, model_key)


def ensure_model_metadata_cache() -> bool:
    """Ensure the local model catalog exists before serving config requests."""

    if _load_catalog(refresh=False):
        return True

    return refresh_model_metadata_cache()


def refresh_model_metadata_cache() -> bool:
    """Fetch the remote model catalog and update the local cache when available."""

    return bool(_load_catalog(refresh=True))


def _load_catalog(*, refresh: bool) -> dict[str, Any]:
    global _CATALOG_CACHE

    if _CATALOG_CACHE is not None and not refresh:
        return _CATALOG_CACHE

    cache_path = _cache_path()
    if cache_path.exists():
        cached = _read_catalog(cache_path)
        if cached and not refresh:
            _CATALOG_CACHE = cached
            return cached

    if not refresh:
        _CATALOG_CACHE = {}
        return {}

    fetched = _fetch_catalog()
    if fetched:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(fetched, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        _CATALOG_CACHE = fetched
        return fetched

    cached = _read_catalog(cache_path)
    _CATALOG_CACHE = cached
    return cached


def _cache_path() -> Path:
    return get_settings().data_dir / MODEL_METADATA_CACHE_NAME


def _read_catalog(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


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


def _match_model_metadata(
    catalog: dict[str, Any],
    provider: str,
    model: str,
) -> ModelMetadata | None:
    best_score = 0
    best_metadata: ModelMetadata | None = None

    for candidate_name, value in catalog.items():
        if candidate_name == "sample_spec" or not isinstance(value, dict):
            continue

        metadata = _metadata_from_catalog_item(value)
        if metadata is None:
            continue

        score = _model_match_score(
            provider=provider,
            model=model,
            candidate_name=str(candidate_name),
            candidate_provider=str(value.get("litellm_provider") or ""),
        )
        if score > best_score:
            best_score = score
            best_metadata = metadata

    return best_metadata if best_score >= 70 else None


def _metadata_from_catalog_item(value: dict[str, Any]) -> ModelMetadata | None:
    context_window_tokens = _positive_int(value.get("max_input_tokens"))
    max_output_tokens = _positive_int(value.get("max_output_tokens"))

    if context_window_tokens is None and max_output_tokens is None:
        return None

    return ModelMetadata(
        context_window_tokens=context_window_tokens,
        max_output_tokens=max_output_tokens,
    )


def _model_match_score(
    *,
    provider: str,
    model: str,
    candidate_name: str,
    candidate_provider: str,
) -> int:
    normalized_model = _normalize_model_name(model)
    normalized_candidate = _normalize_model_name(candidate_name)
    candidate_tail = _normalize_model_name(candidate_name.rsplit("/", 1)[-1])

    if not normalized_model:
        return 0

    score = 0
    if model == candidate_name.lower():
        score = 100
    elif normalized_model == normalized_candidate:
        score = 96
    elif normalized_model == candidate_tail:
        score = 94
    elif normalized_model in normalized_candidate:
        score = 80
    elif normalized_candidate in normalized_model:
        score = 72

    if score and provider:
        normalized_provider = _normalize_model_name(provider)
        catalog_provider = _normalize_model_name(candidate_provider)
        candidate_prefix = _normalize_model_name(candidate_name.split("/", 1)[0])
        if normalized_provider in {catalog_provider, candidate_prefix}:
            score += 6

    return score


def _normalize_model_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0 and value.is_integer():
        return int(value)
    return None
