from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ModelContextReference:
    """Catalog context limit for reference, independent of deployed settings."""

    status: Literal["found", "not_found", "ambiguous"]
    context_window_tokens: int | None = None
    matched_model: str | None = None
    source: Literal["models.dev", "litellm"] | None = None


def normalize_base_context_models(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise ValueError("Model-only catalog must be an object.")
    models: dict[str, dict[str, Any]] = {}
    for model_id, value in raw.items():
        if (
            not _valid_model_id(model_id)
            or not isinstance(value, dict)
            or value.get("id") != model_id
        ):
            continue
        limits = value.get("limit")
        context = limits.get("context") if isinstance(limits, dict) else None
        if type(context) is not int or context <= 0:
            continue
        item: dict[str, Any] = {"contextWindowTokens": context}
        aliases = set()
        weights = value.get("weights")
        if isinstance(weights, list):
            for weight in weights:
                if not isinstance(weight, dict):
                    continue
                alias = _hugging_face_repository(weight.get("url"))
                if alias is not None and alias != model_id:
                    aliases.add(alias)
        if aliases:
            item["aliases"] = sorted(aliases)
        models[model_id] = item
    if not models:
        raise ValueError("Model-only catalog contains no usable context limits.")
    return models


def normalize_ollama_context_models(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for source_key, value in raw.items():
        if not isinstance(source_key, str) or not isinstance(value, dict):
            continue
        prefix, separator, model = source_key.partition("/")
        if (
            prefix not in {"ollama", "ollama_chat"}
            or value.get("litellm_provider") != prefix
            or not separator
            or not _valid_model_id(model)
            or value.get("mode") not in {"chat", "completion"}
        ):
            continue
        context = value.get("max_input_tokens")
        if type(context) is int and context > 0:
            models[source_key] = {
                "contextWindowTokens": context,
                "aliases": [model],
            }
    return models


def valid_context_models(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for model_id, item in value.items():
        if not _valid_model_id(model_id) or not isinstance(item, dict):
            return False
        if item.keys() - {"contextWindowTokens", "aliases"}:
            return False
        context = item.get("contextWindowTokens")
        if type(context) is not int or context <= 0:
            return False
        if "aliases" in item:
            aliases = item["aliases"]
            if (
                not isinstance(aliases, list)
                or not all(_valid_model_id(alias) for alias in aliases)
                or len(set(aliases)) != len(aliases)
            ):
                return False
    return True


def resolve_context_reference(
    provider: str,
    model: str,
    base_models: dict[str, Any],
    ollama_models: dict[str, Any],
) -> ModelContextReference:
    model = model.strip().casefold()
    if not model:
        return ModelContextReference("not_found")
    matches: set[tuple[str, int, Literal["models.dev", "litellm"]]] = set()
    for model_id, item in base_models.items():
        names = [name.casefold() for name in [model_id, *item.get("aliases", [])]]
        if model in names or (
            "/" not in model and any(name.rsplit("/", 1)[-1] == model for name in names)
        ):
            matches.add((model_id, item["contextWindowTokens"], "models.dev"))
    if provider.strip().casefold() == "ollama":
        for model_id, item in ollama_models.items():
            names = [name.casefold() for name in [model_id, *item.get("aliases", [])]]
            if model in names:
                matches.add((model_id, item["contextWindowTokens"], "litellm"))
    if not matches:
        return ModelContextReference("not_found")
    if len(matches) != 1:
        return ModelContextReference("ambiguous")
    matched_model, context, source = matches.pop()
    return ModelContextReference(
        "found",
        context_window_tokens=context,
        matched_model=matched_model,
        source=source,
    )


def _valid_model_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _hugging_face_repository(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme != "https" or url.netloc != "huggingface.co":
        return None
    path = url.path.strip("/")
    components = path.split("/")
    if len(components) != 2 or any(
        not _valid_model_id(component) or component in {".", ".."}
        for component in components
    ):
        return None
    return path
