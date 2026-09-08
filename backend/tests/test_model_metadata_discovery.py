from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services import model_metadata, model_providers


def test_discovery_metadata_work_does_not_grow_per_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_ids = [f"gpt-test-{index:04d}" for index in range(500)]
    now = datetime.now(UTC).isoformat()
    model_metadata._set_memory_cache(
        model_metadata._new_cache(
            {
                "openai": {
                    model_id: {"contextWindowTokens": 128_000, "maxOutputTokens": 8_192}
                    for model_id in model_ids
                }
            },
            now,
            {"openai": {}},
            now,
        )
    )
    monkeypatch.setattr(
        model_providers,
        "_get_json",
        lambda *_args, **_kwargs: {
            "data": [{"id": model_id} for model_id in reversed(model_ids)],
        },
    )
    merge_count = 0
    merge = model_metadata._merge_reasoning_metadata

    def count_merges(
        models: dict[str, dict[str, Any]],
        reasoning: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        nonlocal merge_count
        merge_count += 1
        return merge(models, reasoning)

    monkeypatch.setattr(model_metadata, "_merge_reasoning_metadata", count_merges)
    models = model_providers.discover_provider_models(
        provider_id="openai",
        api_family="openai_responses",
        api_url="https://provider.invalid",
        api_key="test-only",
    )

    assert [model.id for model in models] == model_ids
    assert all(model.context_window_tokens == 128_000 for model in models)
    assert all(model.max_output_tokens == 8_192 for model in models)
    assert merge_count == 1


@pytest.mark.parametrize("litellm_fresh", [True, False])
@pytest.mark.parametrize("reasoning_fresh", [True, False])
def test_discovery_preserves_source_precedence_after_metadata_expires(
    monkeypatch: pytest.MonkeyPatch,
    litellm_fresh: bool,
    reasoning_fresh: bool,
) -> None:
    now = datetime.now(UTC)
    stale = (now - timedelta(days=30)).isoformat()
    model_metadata._set_memory_cache(
        model_metadata._new_cache(
            {
                "qwen": {
                    "Qwen-Test": {
                        "contextWindowTokens": 64_000,
                        "maxOutputTokens": 4_096,
                        "supportsImage": True,
                        "supportsThinking": True,
                        "supportsTools": True,
                        "supportsStreaming": True,
                        "canDisableThinking": False,
                    },
                    "qwen-provider": {
                        "contextWindowTokens": 64_000,
                        "maxOutputTokens": 4_096,
                        "supportsImage": True,
                        "supportsTools": True,
                        "supportsStreaming": True,
                        "supportsThinking": True,
                    },
                    "qwen-off": {
                        "contextWindowTokens": 64_000,
                        "supportsThinking": True,
                    },
                }
            },
            now.isoformat() if litellm_fresh else stale,
            {
                "qwen": {
                    "qwen-test": {"canDisableThinking": True},
                    "qwen-off": {"canDisableThinking": True},
                }
            },
            now.isoformat() if reasoning_fresh else stale,
        )
    )
    monkeypatch.setattr(
        model_providers,
        "_get_json",
        lambda *_, **__: {
            "data": [
                {"id": "qwen-test"},
                {"id": "qwen-off"},
                {
                    "id": "qwen-provider",
                    "max_input_tokens": 128_000,
                    "max_output_tokens": 8_192,
                    "supportsImage": False,
                    "supportsTools": False,
                    "supportsStreaming": False,
                    "canDisableThinking": False,
                },
                {"id": "qwen-unknown"},
                {"id": "text-embedding-model"},
            ],
        },
    )
    models = model_providers.discover_provider_models(
        provider_id="qwen",
        api_family="openai_compatible_chat",
        api_url="https://provider.invalid",
        api_key="test-only",
    )
    by_id = {model.id: model for model in models}

    assert list(by_id) == ["qwen-off", "qwen-provider", "qwen-test", "qwen-unknown"]
    metadata_model = by_id["qwen-test"]
    assert metadata_model.context_window_tokens == 64_000
    assert metadata_model.max_output_tokens == 4_096
    assert metadata_model.metadata_source == "litellm"
    assert metadata_model.supports_image
    assert metadata_model.supports_tools
    assert metadata_model.supports_streaming
    assert metadata_model.available_thinking_modes == ("auto",)
    assert by_id["qwen-off"].available_thinking_modes == ("auto", "off")
    provider_model = by_id["qwen-provider"]
    assert provider_model.context_window_tokens == 128_000
    assert provider_model.max_output_tokens == 8_192
    assert provider_model.metadata_source == "provider"
    assert not provider_model.supports_image
    assert not provider_model.supports_tools
    assert not provider_model.supports_streaming
    assert provider_model.available_thinking_modes == ("auto",)
    assert by_id["qwen-unknown"].context_window_tokens == 32_768
    assert by_id["qwen-unknown"].metadata_source == "fallback"


def test_metadata_model_ids_preserve_punctuation() -> None:
    now = datetime.now(UTC).isoformat()
    model_metadata._set_memory_cache(
        model_metadata._new_cache(
            {
                "openai": {
                    "gpt-test": {"contextWindowTokens": 64_000},
                    "gpt test": {"contextWindowTokens": 32_768},
                    "gpt.test": {"contextWindowTokens": 16_384},
                }
            },
            now,
            {},
            now,
        )
    )
    metadata = model_metadata.resolve_models_metadata(
        " OpenAI ",
        [" GPT-Test ", "gpt.test", "gpt test", "gpt_test", "missing", ""],
    )

    assert {key: item.context_window_tokens for key, item in metadata.items()} == {
        " GPT-Test ": 64_000,
        "gpt.test": 16_384,
        "gpt test": 32_768,
    }


def test_repeated_discovery_misses_do_not_fetch_public_catalogs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(side_effect=AssertionError("discovery must use local metadata"))
    monkeypatch.setattr(model_metadata, "_fetch_catalog", fetch)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", fetch)
    monkeypatch.setattr(
        model_providers, "_get_json", lambda *_, **__: {"data": [{"id": "unknown"}]}
    )

    for _ in range(3):
        models = model_providers.discover_provider_models(
            provider_id="openai",
            api_family="openai_responses",
            api_url="https://api.openai.com/v1",
            api_key="test-only",
        )
        assert [model.id for model in models] == ["unknown"]
    fetch.assert_not_called()
