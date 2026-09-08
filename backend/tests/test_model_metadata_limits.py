import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.services import model_metadata, model_providers
from app.services.model_discovery_cache import (
    get_cached_provider_model,
    write_cached_provider_models,
)


def _catalogs():
    lite = {
        "gpt-test": {
            "litellm_provider": "openai",
            "max_input_tokens": 272_000,
            "max_output_tokens": 128_000,
            "supports_function_calling": True,
        },
        "gemini-test": {
            "litellm_provider": "gemini",
            "max_input_tokens": 1_048_576,
            "max_output_tokens": 65_536,
        },
    }
    models_dev = {
        "models": {
            "openai/base-test": {
                "id": "openai/base-test",
                "limit": {"context": 400_000},
            }
        },
        "providers": {
            "openai": {
                "models": {
                    "gpt-test": {
                        "id": "gpt-test",
                        "reasoning": True,
                        "limit": {
                            "context": 400_000,
                            "input": 272_000,
                            "output": 128_000,
                        },
                    }
                }
            },
            "google": {
                "models": {
                    "gemini-test": {
                        "id": "gemini-test",
                        "reasoning_options": ["none", "low"],
                        "limit": {"context": 1_048_576, "output": 65_536},
                    }
                }
            },
        },
    }
    return lite, models_dev


def test_snapshot_separates_shared_context_and_input_without_inferring_capabilities():
    lite, models_dev = _catalogs()
    snapshot = model_metadata.build_model_metadata_snapshot(
        lite, models_dev, fetched_at=datetime.now(UTC).isoformat()
    )
    model_metadata._set_memory_cache(snapshot)
    openai = model_metadata.resolve_model_metadata("openai", "gpt-test")
    assert openai.context_window_tokens == 272_000
    assert openai.shared_context_window_tokens == 400_000
    assert openai.max_output_tokens == 128_000
    assert openai.supports_thinking is None
    assert openai.can_disable_thinking is None
    google = model_metadata.resolve_model_metadata("google", "gemini-test")
    assert google.context_window_tokens == 1_048_576
    assert google.shared_context_window_tokens is None
    assert google.max_output_tokens == 65_536


def test_shared_context_survives_refresh_restart_and_other_source_failure(monkeypatch):
    lite, models_dev = _catalogs()
    monkeypatch.setattr(model_metadata, "_fetch_catalog", AsyncMock(return_value=lite))
    fetch_limits = AsyncMock(return_value=models_dev)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", fetch_limits)
    assert asyncio.run(model_metadata.refresh_model_metadata_cache())
    model_metadata._CATALOG_CACHE = None
    before = model_metadata.resolve_model_metadata("openai", "gpt-test")
    assert before.shared_context_window_tokens == 400_000
    cache = deepcopy(model_metadata._load_cache())
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    for catalog in cache["catalogs"].values():
        catalog["fetchedAt"] = stale
    model_metadata._set_memory_cache(cache)
    fetch_limits.return_value = {}
    lite["gpt-test"]["max_output_tokens"] = 100_000
    assert asyncio.run(model_metadata.refresh_model_metadata_cache())
    model_metadata._CATALOG_CACHE = None
    after = model_metadata.resolve_model_metadata("openai", "gpt-test")
    assert after.shared_context_window_tokens == 400_000
    assert after.max_output_tokens == 100_000


def test_provider_total_context_has_precedence_and_roundtrips_discovery_cache():
    lite, models_dev = _catalogs()
    snapshot = model_metadata.build_model_metadata_snapshot(
        lite, models_dev, fetched_at=datetime.now(UTC).isoformat()
    )
    model_metadata._set_memory_cache(snapshot)
    metadata = model_metadata.resolve_model_metadata("openai", "gpt-test")
    model = model_providers._normalize_discovered_model(
        "openai",
        {"id": "gpt-test", "context_window": 300_000, "max_input_tokens": 250_000},
        metadata,
    )
    assert model.shared_context_window_tokens == 300_000
    assert model.context_window_tokens == 250_000
    write_cached_provider_models("openai", [model])
    assert get_cached_provider_model("openai", "gpt-test") == model


@pytest.mark.parametrize("invalid", [True, 0, -1, "128000", 1.5])
def test_cache_rejects_invalid_shared_context_limit(tmp_path, invalid):
    import json

    lite, models_dev = _catalogs()
    snapshot = model_metadata.build_model_metadata_snapshot(
        lite, models_dev, fetched_at=datetime.now(UTC).isoformat()
    )
    snapshot["catalogs"]["modelsDev"]["providers"]["openai"]["gpt-test"][
        "sharedContextWindowTokens"
    ] = invalid
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(snapshot))
    cache = model_metadata._read_cache(path)
    assert "modelsDev" not in cache["catalogs"]
    assert "litellm" in cache["catalogs"]


def test_anthropic_shared_input_boundary_precedes_larger_directory_context():
    lite, models_dev = _catalogs()
    lite["anthropic/claude-test"] = {
        "litellm_provider": "anthropic",
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
    }
    lite["openrouter/anthropic/claude-test"] = {
        "litellm_provider": "openrouter",
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 128_000,
    }
    models_dev["providers"]["anthropic"] = {
        "models": {
            "claude-test": {
                "id": "claude-test",
                "limit": {"context": 1_000_000, "output": 64_000},
            }
        }
    }
    snapshot = model_metadata.build_model_metadata_snapshot(
        lite, models_dev, fetched_at=datetime.now(UTC).isoformat()
    )
    model_metadata._set_memory_cache(snapshot)
    metadata = model_metadata.resolve_model_metadata("anthropic", "claude-test")
    assert metadata.shared_context_window_tokens == 200_000
    assert metadata.max_output_tokens == 64_000
    assert (
        model_metadata.resolve_model_metadata("anthropic", "anthropic/claude-test")
        is None
    )
    discovered = model_providers._normalize_discovered_model(
        "anthropic",
        {"id": "claude-test", "max_input_tokens": 160_000, "context_window": 1_000_000},
        metadata,
    )
    assert discovered.shared_context_window_tokens == 160_000
