import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.connection import connect
from app.services import model_metadata, model_providers
from app.services.llm.config import resolve_agent_llm_config
from app.services.model_discovery_cache import (
    MODEL_DISCOVERY_CACHE_NAME,
    read_cached_provider_models,
    write_cached_provider_models,
)
from app.services.model_metadata import (
    ModelMetadata,
    explicit_thinking_off_capability,
)
from app.services.model_providers import DiscoveredModel, enrich_selected_model
from app.services.thinking import can_project_thinking_off


def _write_two_source_metadata_cache(
    tmp_path: Path,
    *,
    litellm_model: dict[str, object],
    reasoning_model: dict[str, object],
) -> Path:
    cache_path = tmp_path / model_metadata.MODEL_METADATA_CACHE_NAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": model_metadata.MODEL_METADATA_CACHE_VERSION,
                "source": model_metadata.MODEL_METADATA_CACHE_SOURCE,
                "catalogs": {
                    "litellm": {
                        "contextModels": {},
                        "fetchedAt": "2020-01-01T00:00:00+00:00",
                        "providers": {"openai": {"gpt-partial": litellm_model}},
                    },
                    "modelsDev": {
                        "contextModels": {},
                        "fetchedAt": "2020-01-01T00:00:00+00:00",
                        "providers": {"openai": {"gpt-partial": reasoning_model}},
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    model_metadata._CATALOG_CACHE = None
    return cache_path


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"supports_none_reasoning_effort": True}, True),
        ({"reasoning_options": [{"type": "toggle"}]}, True),
        (
            {
                "reasoning_options": [
                    {"type": "effort", "values": ["none", "low"]},
                ],
            },
            True,
        ),
        ({"reasoning_options": [{"type": "effort", "values": ["minimal"]}]}, False),
        ({"supported_reasoning_efforts": ["minimal", "low"]}, False),
        ({"supports_reasoning": True}, None),
        ({"thinking_always_on": True}, False),
        ({"reasoning_effort_levels": ["none", "low"]}, True),
        ({"reasoning_effort_levels": ["minimal", "low"]}, False),
    ],
)
def test_explicit_thinking_off_capability_requires_none_or_toggle(
    metadata: dict[str, object],
    expected: bool | None,
) -> None:
    assert explicit_thinking_off_capability(metadata) is expected


@pytest.mark.parametrize(
    ("provider", "api_family", "base_url", "model"),
    [
        ("openai", "openai_responses", "https://api.openai.com/v1", "gpt-off"),
        ("xai", "openai_responses", "https://api.x.ai/v1", "grok-off"),
        (
            "anthropic",
            "anthropic_messages",
            "https://api.anthropic.com/v1",
            "claude-off",
        ),
        (
            "qwen",
            "openai_compatible_chat",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen-off",
        ),
        (
            "deepseek",
            "openai_compatible_chat",
            "https://api.deepseek.com",
            "deepseek-off",
        ),
        (
            "glm",
            "openai_compatible_chat",
            "https://open.bigmodel.cn/api/paas/v4",
            "glm-off",
        ),
        (
            "minimax",
            "openai_compatible_chat",
            "https://api.minimaxi.com/v1",
            "MiniMax-M3",
        ),
    ],
)
def test_native_off_projection_requires_one_registered_adapter_target(
    provider: str,
    api_family: str,
    base_url: str,
    model: str,
) -> None:
    assert can_project_thinking_off(
        provider=provider,
        provider_kind="cloud",
        api_family=api_family,
        base_url=base_url,
        model=model,
    )


@pytest.mark.parametrize(
    ("provider", "provider_kind", "api_family", "base_url", "model"),
    [
        (
            "moonshot",
            "cloud",
            "openai_compatible_chat",
            "https://api.moonshot.ai/v1",
            "kimi-k3",
        ),
        (
            "google",
            "cloud",
            "google_gemini",
            "https://generativelanguage.googleapis.com/v1",
            "gemini-thinking",
        ),
        (
            "minimax",
            "cloud",
            "openai_compatible_chat",
            "https://api.minimaxi.com/v1",
            "MiniMax-M2",
        ),
        (
            "openai",
            "custom",
            "openai_responses",
            "https://api.openai.com/v1",
            "gpt-off",
        ),
        (
            "openai",
            "cloud",
            "openai_responses",
            "https://gateway.example.test/v1",
            "gpt-off",
        ),
    ],
)
def test_native_off_projection_rejects_unregistered_runtime_targets(
    provider: str,
    provider_kind: str,
    api_family: str,
    base_url: str,
    model: str,
) -> None:
    assert not can_project_thinking_off(
        provider=provider,
        provider_kind=provider_kind,
        api_family=api_family,
        base_url=base_url,
        model=model,
    )


def test_models_dev_reasoning_options_enrich_source_neutral_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={
                "openai/gpt-off": {
                    "litellm_provider": "openai",
                    "supports_reasoning": True,
                },
                "openai/gpt-minimal": {
                    "litellm_provider": "openai",
                    "supports_reasoning": True,
                },
            }
        ),
    )
    monkeypatch.setattr(
        model_metadata,
        "_fetch_reasoning_catalog",
        AsyncMock(
            return_value={
                "providers": {
                    "openai": {
                        "models": {
                            "gpt-off": {
                                "id": "gpt-off",
                                "reasoning_options": [{"type": "toggle"}],
                            },
                            "gpt-minimal": {
                                "id": "gpt-minimal",
                                "reasoning_options": [
                                    {"type": "effort", "values": ["minimal", "low"]},
                                ],
                            },
                        },
                    },
                },
                "models": {
                    "openai/base-test": {
                        "id": "openai/base-test",
                        "limit": {"context": 128000},
                    }
                },
            }
        ),
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    off = model_metadata.resolve_model_metadata("openai", "gpt-off")
    minimal = model_metadata.resolve_model_metadata("openai", "gpt-minimal")

    assert off is not None and off.can_disable_thinking is True
    assert minimal is not None and minimal.can_disable_thinking is False
    get_settings.cache_clear()


def test_litellm_only_refresh_preserves_stale_off_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    cache_path = _write_two_source_metadata_cache(
        tmp_path,
        litellm_model={
            "sourceKey": "openai/gpt-partial",
            "contextWindowTokens": 100,
            "supportsThinking": True,
        },
        reasoning_model={
            "sourceKey": "models.dev:openai/gpt-partial",
            "canDisableThinking": True,
        },
    )
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={
                "openai/gpt-partial": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 200,
                    "supports_reasoning": True,
                },
            }
        ),
    )
    monkeypatch.setattr(
        model_metadata, "_fetch_reasoning_catalog", AsyncMock(return_value={})
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    metadata = model_metadata.resolve_model_metadata("openai", "gpt-partial")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert metadata is not None
    assert metadata.context_window_tokens == 200
    assert metadata.can_disable_thinking is True
    assert cache["catalogs"]["litellm"]["fetchedAt"] != ("2020-01-01T00:00:00+00:00")
    assert cache["catalogs"]["modelsDev"]["fetchedAt"] == ("2020-01-01T00:00:00+00:00")
    assert model_metadata._cache_sources_are_fresh(cache) is False
    get_settings.cache_clear()


def test_models_dev_only_refresh_preserves_litellm_limits_and_explicit_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    cache_path = _write_two_source_metadata_cache(
        tmp_path,
        litellm_model={
            "sourceKey": "openai/gpt-partial",
            "contextWindowTokens": 100,
            "supportsThinking": True,
            "canDisableThinking": True,
        },
        reasoning_model={
            "sourceKey": "models.dev:openai/gpt-partial",
            "canDisableThinking": True,
        },
    )
    monkeypatch.setattr(model_metadata, "_fetch_catalog", AsyncMock(return_value={}))
    monkeypatch.setattr(
        model_metadata,
        "_fetch_reasoning_catalog",
        AsyncMock(
            return_value={
                "providers": {
                    "openai": {
                        "models": {
                            "gpt-partial": {
                                "id": "gpt-partial",
                                "reasoning": True,
                                "reasoning_options": [
                                    {"type": "effort", "values": ["minimal", "low"]},
                                ],
                            },
                        },
                    },
                },
                "models": {
                    "openai/base-test": {
                        "id": "openai/base-test",
                        "limit": {"context": 128000},
                    }
                },
            }
        ),
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True
    metadata = model_metadata.resolve_model_metadata("openai", "gpt-partial")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert metadata is not None
    assert metadata.context_window_tokens == 100
    assert metadata.can_disable_thinking is True
    assert cache["catalogs"]["litellm"]["fetchedAt"] == ("2020-01-01T00:00:00+00:00")
    assert cache["catalogs"]["modelsDev"]["fetchedAt"] != ("2020-01-01T00:00:00+00:00")
    assert model_metadata._cache_sources_are_fresh(cache) is False
    get_settings.cache_clear()


def test_future_metadata_timestamps_do_not_authorize_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    cache_path = _write_two_source_metadata_cache(
        tmp_path,
        litellm_model={
            "sourceKey": "openai/gpt-partial",
            "supportsThinking": True,
        },
        reasoning_model={
            "sourceKey": "models.dev:openai/gpt-partial",
            "canDisableThinking": True,
        },
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["catalogs"]["litellm"]["fetchedAt"] = "2999-01-01T00:00:00+00:00"
    cache["catalogs"]["modelsDev"]["fetchedAt"] = "2999-01-01T00:00:00+00:00"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    model_metadata._CATALOG_CACHE = None

    metadata = model_metadata.resolve_model_metadata("openai", "gpt-partial")

    assert metadata is None
    assert model_metadata._cache_sources_are_fresh(cache) is False
    get_settings.cache_clear()


def test_refresh_rebuilds_successful_source_for_every_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    cache_path = _write_two_source_metadata_cache(
        tmp_path,
        litellm_model={
            "sourceKey": "openai/gpt-partial",
            "contextWindowTokens": 100,
        },
        reasoning_model={
            "sourceKey": "models.dev:openai/gpt-partial",
            "canDisableThinking": True,
        },
    )
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["catalogs"]["litellm"]["providers"]["qwen"] = {
        "qwen-stale": {
            "sourceKey": "qwen/qwen-stale",
            "contextWindowTokens": 999,
        },
    }
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    model_metadata._CATALOG_CACHE = None
    monkeypatch.setattr(
        model_metadata,
        "_fetch_catalog",
        AsyncMock(
            return_value={
                "openai/gpt-partial": {
                    "litellm_provider": "openai",
                    "max_input_tokens": 200,
                },
            }
        ),
    )
    monkeypatch.setattr(
        model_metadata, "_fetch_reasoning_catalog", AsyncMock(return_value={})
    )

    assert asyncio.run(model_metadata.refresh_model_metadata_cache()) is True

    assert model_metadata.resolve_model_metadata("qwen", "qwen-stale") is None
    get_settings.cache_clear()


@pytest.mark.parametrize("provider", ["google", "moonshot"])
def test_catalog_toggle_is_not_advertised_without_an_enabled_wire_projection(
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        model_providers,
        "resolve_model_metadata",
        lambda *_: ModelMetadata(
            supports_thinking=True,
            can_disable_thinking=True,
        ),
    )

    model = enrich_selected_model(provider_id=provider, model_id="reasoning-model")

    assert model.available_thinking_modes == ("auto",)


def test_cloud_config_persists_verified_off_and_resolves_native_off(
    client: TestClient,
) -> None:
    write_cached_provider_models(
        "openai",
        [
            DiscoveredModel(
                id="gpt-off",
                label="gpt-off",
                context_window_tokens=131_072,
                max_output_tokens=8_192,
                supports_image=True,
                thinking_control="provider_default",
                metadata_source="catalog",
                available_thinking_modes=("auto", "off"),
            ),
        ],
    )

    response = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "cloud",
            "apiFamily": "openai_responses",
            "nickname": "No reasoning",
            "apiKey": "sk-off-secret",
            "model": "gpt-off",
            "apiUrl": "https://api.openai.com/v1",
            "thinkingMode": "off",
        },
    )

    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["thinkingMode"] == "off"
    assert saved["availableThinkingModes"] == ["auto", "off"]

    with connect() as conn:
        row = conn.execute(
            """
            SELECT thinking_mode, can_disable_thinking
            FROM llm_configs
            WHERE client_id = ?
            """,
            (saved["id"],),
        ).fetchone()
        runtime = resolve_agent_llm_config(conn, saved["id"])

    assert row is not None
    assert row["thinking_mode"] == "off"
    assert row["can_disable_thinking"] == 1
    assert runtime is not None and runtime.thinking_control == "native_off"


def test_unsupported_off_is_rejected_without_mutating_model_selection(
    client: TestClient,
) -> None:
    write_cached_provider_models(
        "openai",
        [
            DiscoveredModel(
                id="gpt-off",
                label="gpt-off",
                context_window_tokens=131_072,
                max_output_tokens=8_192,
                supports_image=True,
                thinking_control="provider_default",
                metadata_source="catalog",
                available_thinking_modes=("auto", "off"),
            ),
            DiscoveredModel(
                id="gpt-auto-only",
                label="gpt-auto-only",
                context_window_tokens=131_072,
                max_output_tokens=8_192,
                supports_image=True,
                thinking_control="provider_default",
                metadata_source="catalog",
            ),
        ],
    )
    created_response = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "cloud",
            "apiFamily": "openai_responses",
            "nickname": "Switching model",
            "apiKey": "sk-switch-secret",
            "model": "gpt-off",
            "apiUrl": "https://api.openai.com/v1",
            "thinkingMode": "off",
        },
    )
    assert created_response.status_code == 200
    created = created_response.json()["data"]

    rejected = client.post(
        "/api/model-configs",
        json={
            **created,
            "apiKey": None,
            "model": "gpt-auto-only",
        },
    )

    assert rejected.status_code == 400
    assert rejected.json()["message"] == "MODEL_CONFIG_THINKING_MODE_UNSUPPORTED"
    with connect() as conn:
        persisted = conn.execute(
            """
            SELECT model, thinking_mode
            FROM llm_configs
            WHERE client_id = ?
            """,
            (created["id"],),
        ).fetchone()
    assert persisted is not None
    assert tuple(persisted) == ("gpt-off", "off")

    normalized = client.post(
        "/api/model-configs",
        json={
            **created,
            "apiKey": None,
            "model": "gpt-auto-only",
            "thinkingMode": "auto",
        },
    )
    assert normalized.status_code == 200
    assert normalized.json()["data"]["thinkingMode"] == "auto"
    assert normalized.json()["data"]["availableThinkingModes"] == ["auto"]


@pytest.mark.parametrize(
    "untrusted_fetched_at",
    ["2020-01-01T00:00:00+00:00", "2999-01-01T00:00:00+00:00"],
)
def test_untrusted_discovery_cache_time_downgrades_off_until_provider_refresh(
    client: TestClient,
    untrusted_fetched_at: str,
) -> None:
    write_cached_provider_models(
        "openai",
        [
            DiscoveredModel(
                id="gpt-expired-off",
                label="gpt-expired-off",
                context_window_tokens=131_072,
                max_output_tokens=8_192,
                supports_image=True,
                thinking_control="provider_default",
                metadata_source="catalog",
                available_thinking_modes=("auto", "off"),
            ),
        ],
    )
    cache_path = get_settings().data_dir / MODEL_DISCOVERY_CACHE_NAME / "openai.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["fetchedAt"] = untrusted_fetched_at
    cache_path.write_text(json.dumps(cache), encoding="utf-8")

    cached = read_cached_provider_models("openai")
    response = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "cloud",
            "apiFamily": "openai_responses",
            "nickname": "Expired Off",
            "apiKey": "sk-expired-secret",
            "model": "gpt-expired-off",
            "apiUrl": "https://api.openai.com/v1",
            "thinkingMode": "off",
        },
    )

    assert cached is not None
    assert cached[0].available_thinking_modes == ("auto",)
    assert response.status_code == 400
    assert response.json()["message"] == "MODEL_CONFIG_THINKING_MODE_UNSUPPORTED"


def test_database_rejects_off_without_verified_disable_capability() -> None:
    from app.db.schema import SCHEMA_PATH

    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO llm_configs (
                client_id, name, provider, provider_kind, api_family, model,
                context_window_tokens, thinking_mode, can_disable_thinking
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invalid-off",
                "Invalid Off",
                "openai",
                "cloud",
                "openai_responses",
                "unsupported",
                32_768,
                "off",
                0,
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO llm_configs (
                client_id, name, provider, provider_kind, api_family, model,
                context_window_tokens, supports_thinking, thinking_mode,
                can_disable_thinking
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invalid-capability",
                "Invalid Capability",
                "openai",
                "cloud",
                "openai_responses",
                "unsupported",
                32_768,
                0,
                "auto",
                1,
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO llm_configs (
                client_id, name, provider, provider_kind, api_family, model,
                context_window_tokens, supports_thinking, thinking_mode,
                can_disable_thinking
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "invalid-local-capability",
                "Invalid Local Capability",
                "ollama",
                "local",
                "openai_compatible_chat",
                "local-model",
                32_768,
                1,
                "auto",
                1,
            ),
        )
