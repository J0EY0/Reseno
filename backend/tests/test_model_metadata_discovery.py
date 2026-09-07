from datetime import UTC, datetime, timedelta
from typing import Any

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
    assert merge_count <= 2


@pytest.mark.parametrize(
    ("litellm_fresh", "reasoning_fresh", "allows_off"),
    [
        (True, True, True),
        (False, True, True),
        (True, False, False),
        (False, False, False),
    ],
)
def test_discovery_preserves_metadata_precedence_and_source_freshness(
    monkeypatch: pytest.MonkeyPatch,
    litellm_fresh: bool,
    reasoning_fresh: bool,
    allows_off: bool,
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
                    }
                }
            },
            now.isoformat() if litellm_fresh else stale,
            {
                "qwen": {
                    "qwen.test": {
                        "contextWindowTokens": 999_999,
                        "canDisableThinking": True,
                    }
                }
            },
            now.isoformat() if reasoning_fresh else stale,
        )
    )
    raw_models = [
        {"id": "qwen_test"},
        {
            "id": "qwen-test",
            "max_input_tokens": 128_000,
            "max_output_tokens": 8_192,
            "supportsImage": False,
            "supportsTools": False,
            "supportsStreaming": False,
            "canDisableThinking": False,
        },
        {"id": "unknown-model"},
        {"id": "text-embedding-model"},
    ]
    monkeypatch.setattr(
        model_providers,
        "_get_json",
        lambda *_, **__: {
            "data": raw_models,
        },
    )

    models = model_providers.discover_provider_models(
        provider_id="qwen",
        api_family="openai_compatible_chat",
        api_url="https://provider.invalid",
        api_key="test-only",
    )
    by_id = {model.id: model for model in models}

    assert list(by_id) == ["qwen-test", "qwen_test", "unknown-model"]
    metadata_model = by_id["qwen_test"]
    assert metadata_model.context_window_tokens == 64_000
    assert metadata_model.max_output_tokens == 4_096
    assert metadata_model.metadata_source == "litellm"
    assert metadata_model.supports_image
    assert metadata_model.supports_tools
    assert metadata_model.supports_streaming
    assert ("off" in metadata_model.available_thinking_modes) is allows_off
    provider_model = by_id["qwen-test"]
    assert provider_model.context_window_tokens == 128_000
    assert provider_model.max_output_tokens == 8_192
    assert provider_model.metadata_source == "provider"
    assert not provider_model.supports_image
    assert not provider_model.supports_tools
    assert not provider_model.supports_streaming
    assert provider_model.available_thinking_modes == ("auto",)
    assert by_id["unknown-model"].context_window_tokens == 32_768
    assert by_id["unknown-model"].metadata_source == "fallback"


def test_metadata_aliases_retain_first_sorted_catalog_match() -> None:
    now = datetime.now(UTC).isoformat()
    model_metadata._set_memory_cache(
        model_metadata._new_cache(
            {
                "openai": {
                    "gpt-test": {"contextWindowTokens": 64_000},
                    "gpt test": {"contextWindowTokens": 32_768},
                }
            },
            now,
            {},
            now,
        )
    )

    metadata = model_metadata.resolve_models_metadata(
        " OpenAI ",
        [" GPT_Test ", "gpt.test", "missing", ""],
    )

    assert set(metadata) == {" GPT_Test ", "gpt.test"}
    assert all(item.context_window_tokens == 32_768 for item in metadata.values())
