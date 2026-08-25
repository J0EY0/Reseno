import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import get_args

import pytest

from app.config import get_settings
from app.db.schema import SCHEMA_PATH
from app.services.llm import AgentLlmConfig
from app.services.llm.config import _use_native_web_search, resolve_agent_llm_config
from app.services.model_discovery_cache import write_cached_provider_models
from app.services.model_providers import DiscoveredModel
from app.services.thinking import ThinkingControl


def test_runtime_model_config_exposes_a_typed_thinking_control() -> None:
    field_names = {field.name for field in fields(AgentLlmConfig)}

    assert get_args(ThinkingControl) == (
        "none",
        "provider_default",
        "native_auto",
        "native_budget",
    )
    assert "thinking_control" in field_names
    assert "supports_thinking" not in field_names
    assert "thinking_enabled" not in field_names


@pytest.mark.parametrize(
    ("provider", "provider_kind", "api_family", "model", "supported", "expected"),
    [
        ("openai", "cloud", "openai_responses", "gpt-5.1", True, True),
        ("anthropic", "cloud", "anthropic_messages", "claude-sonnet-4", True, True),
        ("google", "cloud", "google_gemini", "gemini-3.1-pro", True, True),
        ("google", "cloud", "google_gemini", "gemini-2.5-pro", True, False),
        ("openai", "cloud", "openai_responses", "gpt-5.1", False, False),
        ("custom-cloud", "custom", "openai_responses", "gpt-5.1", True, False),
    ],
)
def test_native_web_search_is_selected_once_from_verified_capabilities(
    provider: str,
    provider_kind: str,
    api_family: str,
    model: str,
    supported: bool,
    expected: bool,
) -> None:
    assert (
        _use_native_web_search(
            provider=provider,
            provider_kind=provider_kind,
            api_family=api_family,
            model=model,
            model_supports_web_search=supported,
        )
        is expected
    )


def test_runtime_custom_config_uses_provider_default_for_manual_capability() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO llm_configs (
            client_id,
            name,
            provider,
            provider_kind,
            api_family,
            model,
            base_url,
            max_tokens,
            context_window_tokens,
            supports_thinking
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "runtime-auto",
            "Runtime Auto",
            "custom-cloud",
            "custom",
            "openai_compatible_chat",
            "auto-model",
            "https://example.test/v1",
            2048,
            32768,
            1,
        ),
    )

    selected = resolve_agent_llm_config(conn, {"id": "runtime-auto"})
    default = resolve_agent_llm_config(conn, None)

    assert selected == default
    assert selected is not None
    assert selected.client_id == "runtime-auto"
    assert selected.model == "auto-model"
    assert selected.thinking_control == "provider_default"


@pytest.mark.parametrize(
    ("provider", "provider_kind", "expected_control"),
    [
        ("vllm", "local", "native_auto"),
        ("sglang", "local", "native_auto"),
        ("ollama", "local", "provider_default"),
        ("custom-cloud", "custom", "provider_default"),
    ],
)
def test_runtime_manual_thinking_maps_to_verified_provider_action(
    provider: str,
    provider_kind: str,
    expected_control: ThinkingControl,
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO llm_configs (
            client_id, name, provider, provider_kind, api_family, model,
            base_url, context_window_tokens, supports_thinking
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "manual-thinking",
            "Manual Thinking",
            provider,
            provider_kind,
            "openai_compatible_chat",
            "self-hosted-model",
            "http://localhost:8000/v1",
            32768,
            1,
        ),
    )

    config = resolve_agent_llm_config(conn, {"id": "manual-thinking"})

    assert config is not None
    assert config.thinking_control == expected_control


def test_runtime_anthropic_only_trusts_current_official_adaptive_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        """
        INSERT INTO llm_configs (
            client_id,
            name,
            provider,
            provider_kind,
            api_family,
            model,
            base_url,
            context_window_tokens,
            supports_thinking
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "anthropic-auto",
            "Anthropic Auto",
            "anthropic",
            "cloud",
            "anthropic_messages",
            "claude-example",
            "https://api.anthropic.com/v1",
            200_000,
            1,
        ),
    )

    stale = resolve_agent_llm_config(conn, {"id": "anthropic-auto"})

    assert stale is not None
    assert stale.thinking_control == "none"

    conn.execute(
        "UPDATE llm_configs SET supports_thinking = 0 WHERE client_id = ?",
        ("anthropic-auto",),
    )
    write_cached_provider_models(
        "anthropic",
        [
            DiscoveredModel(
                id="claude-example",
                label="claude-example",
                context_window_tokens=200_000,
                max_output_tokens=64_000,
                supports_image=True,
                thinking_control="native_auto",
                metadata_source="provider",
            ),
        ],
    )

    current = resolve_agent_llm_config(conn, {"id": "anthropic-auto"})

    assert current is not None
    assert current.thinking_control == "native_auto"
    get_settings.cache_clear()
