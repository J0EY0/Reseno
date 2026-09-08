import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.services import model_metadata, model_providers
from app.services.llm.config import resolve_agent_llm_config
from app.services.model_discovery_cache import write_cached_provider_models
from app.services.model_providers import DiscoveredModel

QWEN_MODELS = ("qWeN-next", "QwQ-next", "QVQ-next")
THIRD_PARTY_MODELS = (
    "deepseek-v4-pro",
    "kimi-k3",
    "llama-4",
    "MiniMax/MiniMax-M2.7",
    "glm-5",
    "deepseek-r1-distill-qwen-32b",
)


def test_generated_qwen_catalogs_exclude_bailian_third_party_models() -> None:
    models = (*QWEN_MODELS, *THIRD_PARTY_MODELS)
    litellm = {
        f"dashscope/{model}": {
            "litellm_provider": "dashscope",
            "max_input_tokens": 128_000,
            "supports_reasoning": True,
        }
        for model in models
    }
    litellm["deepseek/deepseek-v4-pro"] = {
        "litellm_provider": "deepseek",
        "max_input_tokens": 128_000,
    }
    reasoning = {
        "providers": {
            "alibaba-cn": {
                "models": {
                    model: {
                        "id": f" {model} ",
                        "reasoning": True,
                        "reasoning_options": [{"type": "toggle"}],
                    }
                    for model in models
                }
            },
            "deepseek": {
                "models": {
                    "deepseek-v4-pro": {"reasoning_options": [{"type": "toggle"}]}
                }
            },
        },
        "models": {
            "alibaba/qwen-next": {
                "id": "alibaba/qwen-next",
                "limit": {"context": 128000},
            }
        },
    }

    snapshot = model_metadata.build_model_metadata_snapshot(
        litellm, reasoning, fetched_at=datetime.now(UTC).isoformat()
    )

    for source in ("litellm", "modelsDev"):
        providers = snapshot["catalogs"][source]["providers"]
        assert set(providers["qwen"]) == set(QWEN_MODELS)
        assert "deepseek-v4-pro" in providers["deepseek"]


def test_fresh_metadata_cache_cannot_restore_qwen_third_party_models(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC).isoformat()
    all_models = (*QWEN_MODELS, *THIRD_PARTY_MODELS)
    snapshot = model_metadata._new_cache(
        {
            "qwen": {model: {"contextWindowTokens": 128_000} for model in all_models},
            "deepseek": {"deepseek-v4-pro": {"contextWindowTokens": 128_000}},
        },
        now,
        {
            "qwen": {model: {"canDisableThinking": True} for model in all_models},
        },
        now,
    )
    cache_path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps(snapshot), encoding="utf-8")

    requested = [f" {model} " for model in all_models]
    found = model_metadata.resolve_models_metadata("qwen", requested)

    assert set(found) == {f" {model} " for model in QWEN_MODELS}
    assert all(item.can_disable_thinking is True for item in found.values())
    assert (
        model_metadata.resolve_model_metadata("deepseek", "deepseek-v4-pro") is not None
    )
    assert cache_path.read_text(encoding="utf-8") == json.dumps(snapshot)


@pytest.mark.parametrize("provider_id", ["qwen", "deepseek"])
def test_discovery_limits_only_the_qwen_provider_to_its_model_family(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    model_ids = (*QWEN_MODELS, *THIRD_PARTY_MODELS)
    monkeypatch.setattr(
        model_providers,
        "_get_json",
        lambda *_, **__: {"data": [{"id": f" {model} "} for model in model_ids]},
    )
    provider = model_providers.get_model_provider(provider_id)
    assert provider is not None and provider.api_family is not None

    models = model_providers.discover_provider_models(
        provider_id=provider_id,
        api_family=provider.api_family,
        api_url=provider.default_base_url,
        api_key="test-only",
    )

    expected = QWEN_MODELS if provider_id == "qwen" else model_ids
    assert [model.id for model in models] == sorted(expected, key=str.lower)


def _discovered_model(model: str) -> DiscoveredModel:
    return DiscoveredModel(
        id=model,
        label=model,
        context_window_tokens=128_000,
        max_output_tokens=8_192,
        supports_image=False,
        thinking_control="none",
        metadata_source="provider",
    )


def test_discovery_api_filters_existing_qwen_cache_without_refetching(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    all_models = (*QWEN_MODELS, *THIRD_PARTY_MODELS)
    cached = [_discovered_model(model) for model in all_models]

    def unexpected_fetch(*_args, **_kwargs):
        raise AssertionError("A populated discovery cache must not require a new fetch")

    monkeypatch.setattr(model_providers, "_get_json", unexpected_fetch)
    for provider_id in ("qwen", "deepseek"):
        write_cached_provider_models(provider_id, cached)
        provider = model_providers.get_model_provider(provider_id)
        assert provider is not None
        response = client.post(
            "/api/model-providers/discover-models",
            json={
                "provider": provider_id,
                "apiFamily": provider.api_family,
                "apiUrl": provider.default_base_url,
                "apiKey": "test-only",
            },
        )
        assert response.status_code == 200
        expected = QWEN_MODELS if provider_id == "qwen" else all_models
        assert {model["id"] for model in response.json()["data"]["models"]} == set(
            expected
        )


@pytest.mark.parametrize("existing_config", [False, True])
def test_qwen_third_party_config_cannot_be_saved_or_resaved(
    client: TestClient,
    existing_config: bool,
) -> None:
    write_cached_provider_models("qwen", [_discovered_model("qwen-next")])
    payload = {
        "provider": "qwen",
        "providerKind": "cloud",
        "apiFamily": "openai_compatible_chat",
        "apiUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "apiKey": "test-only",
        "model": "qwen-next",
    }
    if existing_config:
        created = client.post("/api/model-configs", json=payload)
        assert created.status_code == 200
        config_id = created.json()["data"]["id"]
        with connect() as conn:
            conn.execute(
                "UPDATE llm_configs SET model = ? WHERE client_id = ?",
                ("deepseek-v4-pro", config_id),
            )
        payload.update({"id": config_id, "apiKey": None})
    payload["model"] = "deepseek-v4-pro"
    write_cached_provider_models("qwen", [_discovered_model("deepseek-v4-pro")])

    response = client.post("/api/model-configs", json=payload)

    assert response.status_code == 400
    assert response.json()["message"] == "MODEL_CONFIG_MODEL_NOT_DISCOVERED"
    if existing_config:
        with connect() as conn:
            config = resolve_agent_llm_config(conn, config_id)
        assert config is not None and config.model == "deepseek-v4-pro"


def test_custom_config_can_still_use_a_bailian_third_party_model(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/model-configs",
        json={
            "provider": "custom-cloud",
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "apiUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "apiKey": "test-only",
            "model": "deepseek-v4-pro",
            "contextWindowTokens": 128_000,
            "supportsTools": True,
        },
    )

    assert response.status_code == 200
    config = response.json()["data"]
    assert config["model"] == "deepseek-v4-pro"
    assert config["contextWindowTokens"] == 128_000
    assert config["supportsTools"] is True
