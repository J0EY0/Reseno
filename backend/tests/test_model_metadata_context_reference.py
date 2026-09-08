import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services import model_metadata
from app.services.model_context_reference import (
    normalize_base_context_models,
    normalize_ollama_context_models,
    resolve_context_reference,
    valid_context_models,
)


def _base_models() -> dict:
    return {
        "alibaba/qwen3-32b": {
            "id": "alibaba/qwen3-32b",
            "limit": {"context": 131_072, "output": 16_384},
            "weights": [
                {"url": "https://huggingface.co/Qwen/Qwen3-32B"},
                {"url": "https://huggingface.co/Qwen/Qwen3-32B-FP8"},
            ],
            "reasoning": True,
            "tool_call": True,
        },
    }


def _catalogs() -> tuple[dict, dict]:
    return (
        {
            "gpt-cloud": {
                "litellm_provider": "openai",
                "max_input_tokens": 100_000,
                "supports_none_reasoning_effort": False,
            },
            "ollama/codegemma": {
                "litellm_provider": "ollama",
                "mode": "completion",
                "max_input_tokens": 8_192,
            },
        },
        {
            "providers": {
                "openai": {
                    "models": {
                        "gpt-cloud": {"reasoning_options": [{"type": "toggle"}]},
                    },
                },
            },
            "models": _base_models(),
        },
    )


def _snapshot() -> dict:
    lite, reasoning = _catalogs()
    return model_metadata.build_model_metadata_snapshot(
        lite,
        reasoning,
        fetched_at="2020-01-01T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    "model",
    [
        "alibaba/qwen3-32b",
        "Qwen/Qwen3-32B",
        "Qwen/qwen3-32b",
        " qWeN/QwEn3-32B ",
        "qwen3-32b",
        "Qwen3-32B-FP8",
    ],
)
def test_context_matches_complete_ids_and_explicit_weight_aliases(model: str) -> None:
    models = normalize_base_context_models(_base_models())
    result = resolve_context_reference("lmstudio", model, models, {})
    assert result.status == "found"
    assert result.context_window_tokens == 131_072
    assert result.matched_model == "alibaba/qwen3-32b"
    assert result.source == "models.dev"
    assert set(models["alibaba/qwen3-32b"]) == {"contextWindowTokens", "aliases"}


@pytest.mark.parametrize(
    "model",
    [
        "qwen3:32b",
        "qwen3-8b",
        "Qwen3-32B-Q4_K_M",
        "Qwen3-32B-20250901",
        "bartowski/Qwen3-32B",
        "Qwen3",
        "",
        "  ",
    ],
)
def test_context_does_not_infer_sizes_dates_quantization_or_namespaces(
    model: str,
) -> None:
    result = resolve_context_reference(
        "ollama",
        model,
        normalize_base_context_models(_base_models()),
        {},
    )
    assert result.status == "not_found"
    assert result.context_window_tokens is None
    assert result.matched_model is None
    assert result.source is None


def test_unnamespaced_and_casefold_collisions_are_ambiguous() -> None:
    models = {
        "first/shared": {"contextWindowTokens": 10_000},
        "second/shared": {"contextWindowTokens": 20_000},
        "vendor/Model": {"contextWindowTokens": 30_000},
        "vendor/model": {"contextWindowTokens": 40_000},
    }
    for query in ("shared", "vendor/MODEL"):
        result = resolve_context_reference("custom", query, models, {})
        assert result.status == "ambiguous"
        assert result.context_window_tokens is None
        assert result.matched_model is None
        assert result.source is None
    result = resolve_context_reference("custom", "first/shared", models, {})
    assert result.status == "found" and result.context_window_tokens == 10_000


def test_conflicting_explicit_weight_aliases_are_ambiguous() -> None:
    models = {
        "first/model": {"contextWindowTokens": 10_000, "aliases": ["weights/shared"]},
        "second/model": {"contextWindowTokens": 20_000, "aliases": ["weights/shared"]},
    }
    assert resolve_context_reference("custom", "weights/shared", models, {}).status == (
        "ambiguous"
    )


def test_ollama_explicit_ids_and_cross_source_conflicts() -> None:
    lite, _ = _catalogs()
    lite["ollama/gpt-oss:20b-cloud"] = {
        "litellm_provider": "ollama",
        "mode": "chat",
        "max_input_tokens": 131_072,
    }
    models = normalize_ollama_context_models(lite)
    assert set(models) == {"ollama/codegemma", "ollama/gpt-oss:20b-cloud"}
    found = resolve_context_reference("ollama", "gpt-oss:20b-cloud", {}, models)
    assert found.status == "found" and found.source == "litellm"
    assert resolve_context_reference("lmstudio", "codegemma", {}, models).status == (
        "not_found"
    )
    assert resolve_context_reference("ollama", "gpt-oss:20b", {}, models).status == (
        "not_found"
    )
    base_models = {"google/codegemma": {"contextWindowTokens": 16_384}}
    assert resolve_context_reference(
        "ollama", "codegemma", base_models, models
    ).status == ("ambiguous")


@pytest.mark.parametrize(
    "weight_url",
    [
        "https://huggingface.co.evil.invalid/Qwen/Fake",
        "https://huggingface.co/Qwen/Fake/tree/main",
        "http://huggingface.co/Qwen/Fake",
        "https://huggingface.co/../Fake",
        "https://invalid[host",
        123,
    ],
)
def test_only_explicit_hugging_face_repository_links_become_aliases(weight_url) -> None:
    raw = _base_models()
    raw["alibaba/qwen3-32b"]["weights"] = [{"url": weight_url}]
    models = normalize_base_context_models(raw)
    assert models == {"alibaba/qwen3-32b": {"contextWindowTokens": 131_072}}


@pytest.mark.parametrize("context", [True, False, 0, -1, 32_768.0, "32768", None])
def test_invalid_context_limits_cannot_enter_reference_catalog(context) -> None:
    with pytest.raises(ValueError, match="no usable context limits"):
        normalize_base_context_models(
            {"vendor/model": {"id": "vendor/model", "limit": {"context": context}}},
        )
    assert not valid_context_models({"vendor/model": {"contextWindowTokens": context}})


def test_offline_reference_lookup_preserves_cloud_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    bundled = tmp_path / "bundle.json"
    bundled.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_SNAPSHOT_PATH", bundled)
    fetch = AsyncMock(side_effect=AssertionError("Reference lookup must stay local"))
    monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", fetch)
    result = model_metadata.resolve_model_context_reference(
        "lmstudio", "Qwen/Qwen3-32B"
    )
    assert result.status == "found" and result.context_window_tokens == 131_072
    assert not model_metadata._cache_sources_are_fresh(snapshot)
    assert not (tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME).exists()
    fetch.assert_not_called()
    cloud = model_metadata.resolve_model_metadata("openai", "gpt-cloud")
    assert cloud is not None and cloud.context_window_tokens == 100_000
    assert cloud.can_disable_thinking is False
    assert model_metadata.resolve_model_metadata("ollama", "codegemma") is None
    assert model_metadata.resolve_model_metadata("qwen", "qwen3-32b") is None


@pytest.mark.parametrize("failed_source", ["litellm", "modelsDev"])
def test_refresh_keeps_context_references_with_their_source_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    failed_source: str,
) -> None:
    old = _snapshot()
    model_metadata._set_memory_cache(old)
    lite, reasoning = _catalogs()
    lite["ollama/codegemma"]["max_input_tokens"] = 16_384
    reasoning["models"]["alibaba/qwen3-32b"]["limit"]["context"] = 262_144
    if failed_source == "litellm":
        lite = {}
    else:
        reasoning["models"] = {}
    monkeypatch.setattr(model_metadata, "_fetch_catalog", AsyncMock(return_value=lite))
    monkeypatch.setattr(
        model_metadata,
        "_fetch_reasoning_catalog",
        AsyncMock(return_value=reasoning),
    )
    assert asyncio.run(model_metadata.refresh_model_metadata_cache())
    updated = model_metadata._load_cache()
    assert updated["catalogs"][failed_source] == old["catalogs"][failed_source]
    expected = 262_144 if failed_source == "litellm" else 131_072
    assert (
        model_metadata.resolve_model_context_reference(
            "lmstudio",
            "Qwen/Qwen3-32B",
        ).context_window_tokens
        == expected
    )
    expected = 8_192 if failed_source == "litellm" else 16_384
    assert (
        model_metadata.resolve_model_context_reference(
            "ollama",
            "codegemma",
        ).context_window_tokens
        == expected
    )


def test_invalid_persisted_context_does_not_hide_valid_bundled_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled = tmp_path / "bundle.json"
    bundled.write_text(json.dumps(_snapshot()), encoding="utf-8")
    monkeypatch.setattr(model_metadata, "MODEL_METADATA_SNAPSHOT_PATH", bundled)
    disk = _snapshot()
    disk["catalogs"]["modelsDev"]["fetchedAt"] = datetime.now(UTC).isoformat()
    disk["catalogs"]["modelsDev"]["contextModels"]["alibaba/qwen3-32b"][
        "contextWindowTokens"
    ] = True
    path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(disk), encoding="utf-8")
    assert (
        model_metadata.resolve_model_context_reference(
            "lmstudio",
            "Qwen/Qwen3-32B",
        ).context_window_tokens
        == 131_072
    )
