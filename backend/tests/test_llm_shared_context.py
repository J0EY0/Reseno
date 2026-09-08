import asyncio
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.db.schema import SCHEMA_PATH
from app.schemas.agent import AgentChatRequest
from app.services import model_metadata, model_providers
from app.services.agent.runtime.compaction import prepare_agent_prompt
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.messages import fit_agent_model_turn_prompt
from app.services.llm.adapters.openai_responses import responses_params
from app.services.llm.config import resolve_agent_llm_config
from app.services.llm.output_budget import (
    estimate_prompt_tokens,
    resolve_request_output_budget,
)
from app.services.llm.types import LlmPrompt
from app.services.model_discovery_cache import (
    get_cached_provider_model,
    write_cached_provider_models,
)


def _config_from_bundle(
    monkeypatch, *, model="gpt-4o-2024-08-06", max_tokens=16384, provider="openai"
):
    monkeypatch.setattr(
        model_metadata,
        "MODEL_METADATA_SNAPSHOT_PATH",
        Path(model_metadata.__file__).with_name("model_metadata_snapshot.json"),
    )
    metadata = model_metadata.resolve_model_metadata(provider, model)
    assert metadata is not None
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_PATH.read_text())
        conn.execute(
            """INSERT INTO llm_configs
            (client_id,name,provider,provider_kind,api_family,model,base_url,
             max_tokens,context_window_tokens,supports_tools)
            VALUES ('shared','Shared',?,'cloud',?,?,?, ?,?,0)""",
            (
                provider,
                "anthropic_messages" if provider == "anthropic" else "openai_responses",
                model,
                f"https://api.{provider}.com/v1",
                max_tokens,
                metadata.context_window_tokens,
            ),
        )
        config = resolve_agent_llm_config(conn, "shared")
    assert config is not None
    return config


def test_bundled_gpt4o_limits_reach_real_prompt_and_wire_budget(monkeypatch):
    config = _config_from_bundle(monkeypatch)
    request = AgentChatRequest(
        message={"id": "current", "role": "user", "text": "word " * 94_000},
        resume={"basic": {"name": "Test"}, "sections": []},
    )
    prompt = asyncio.run(prepare_agent_prompt(request, config, AgentRuntimeContext()))
    prompt = fit_agent_model_turn_prompt(request, config, prompt)
    resolved = resolve_request_output_budget(config, prompt)
    params = responses_params(resolved, prompt)
    assert estimate_prompt_tokens(prompt) + params["max_output_tokens"] <= 128_000
    assert resolved.max_tokens == 16_384


def test_separate_gpt51_input_limit_does_not_consume_output_twice(monkeypatch):
    config = _config_from_bundle(monkeypatch, model="gpt-5.1", max_tokens=128_000)
    assert config.context_window_tokens == 272_000
    assert config.shared_context_window_tokens == 400_000
    prompt = LlmPrompt(messages=[{"role": "user", "content": "text " * 200_000}])
    resolved = resolve_request_output_budget(config, prompt)
    assert resolved.request_max_output_tokens == 128_000


def test_shared_cloud_auto_keeps_optional_output_limit_omitted(monkeypatch):
    config = _config_from_bundle(monkeypatch, max_tokens=None)
    prompt = LlmPrompt(messages=[{"role": "user", "content": "text " * 94_000}])
    resolved = resolve_request_output_budget(config, prompt)
    assert "max_output_tokens" not in responses_params(resolved, prompt)


def test_shared_cloud_budget_shrinks_as_tool_results_extend_the_turn(monkeypatch):
    config = _config_from_bundle(monkeypatch)
    prompt = LlmPrompt(messages=[{"role": "user", "content": "text " * 94_000}])
    first = resolve_request_output_budget(config, prompt)
    prompt.messages.extend(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call", "content": "result " * 1000},
        ]
    )
    second = resolve_request_output_budget(config, prompt)
    assert (
        0 < second.request_max_output_tokens < first.request_max_output_tokens < 16384
    )
    assert second.max_tokens == first.max_tokens == config.max_tokens == 16384


@pytest.mark.parametrize("provider_kind", ["local", "custom"])
def test_manual_deployment_context_overrides_public_reference(
    monkeypatch, provider_kind
):
    config = replace(
        _config_from_bundle(monkeypatch),
        provider_kind=provider_kind,
        context_window_tokens=32_000,
        shared_context_window_tokens=128_000,
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "text " * 20_000}])
    resolved = resolve_request_output_budget(config, prompt)
    assert estimate_prompt_tokens(prompt) + resolved.request_max_output_tokens <= 32_000


def test_anthropic_mandatory_auto_output_fits_remaining_shared_context(monkeypatch):
    from app.services.llm.adapters import anthropic_messages

    config = replace(
        _config_from_bundle(monkeypatch, max_tokens=None),
        provider="anthropic",
        api_family="anthropic_messages",
        base_url="https://api.anthropic.com/v1",
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "text " * 94_000}])
    resolved = resolve_request_output_budget(config, prompt)
    payload = anthropic_messages._payload(resolved, prompt.messages)
    assert 0 < payload["max_tokens"] < 16_000
    assert estimate_prompt_tokens(prompt) + payload["max_tokens"] <= 128_000


def test_smaller_current_total_window_is_used_before_prompt_dispatch(monkeypatch):
    from app.services.agent.runtime.context import AgentContextWindowError

    config = replace(
        _config_from_bundle(monkeypatch),
        context_window_tokens=128_000,
        shared_context_window_tokens=32_000,
    )
    request = AgentChatRequest(
        message={"id": "current", "role": "user", "text": "text " * 30_000}
    )
    with pytest.raises(AgentContextWindowError):
        asyncio.run(prepare_agent_prompt(request, config, AgentRuntimeContext()))


def test_provider_discovery_total_context_reaches_runtime_from_disk(monkeypatch):
    _config_from_bundle(monkeypatch)
    discovered = model_providers._normalize_discovered_model(
        "openai",
        {
            "id": "gpt-4o-2024-08-06",
            "context_window": 100_000,
            "max_input_tokens": 96_000,
        },
        None,
    )
    write_cached_provider_models("openai", [discovered])
    assert get_cached_provider_model("openai", discovered.id) == discovered
    config = _config_from_bundle(monkeypatch)
    assert config.shared_context_window_tokens == 100_000


def test_google_independent_input_limit_does_not_reduce_output(monkeypatch):
    config = replace(
        _config_from_bundle(monkeypatch),
        provider="google",
        api_family="google_gemini",
        shared_context_window_tokens=None,
        context_window_tokens=1_048_576,
        max_tokens=65_536,
        model_max_output_tokens=65_536,
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "text " * 810_000}])
    resolved = resolve_request_output_budget(config, prompt)
    assert resolved.request_max_output_tokens == 65_536


@pytest.mark.parametrize(
    (
        "provider",
        "model",
        "input_context",
        "expected_total",
        "thinking_control",
        "source",
    ),
    [
        ("anthropic", "claude-sonnet-4-6", 200_000, 200_000, "native_auto", "provider"),
        ("anthropic", "claude-sonnet-4-6", 32768, 1_000_000, "native_auto", "fallback"),
        ("openai", "gpt-5.1", 272_000, 400_000, "provider_default", "provider"),
    ],
)
def test_existing_discovery_facts_keep_thinking_and_load_missing_total_offline(
    monkeypatch,
    provider,
    model,
    input_context,
    expected_total,
    thinking_control,
    source,
):
    import json

    from app.config import get_settings
    from app.services.model_discovery_cache import MODEL_DISCOVERY_CACHE_NAME

    discovered = model_providers.DiscoveredModel(
        id=model,
        label=model,
        context_window_tokens=input_context,
        max_output_tokens=64_000,
        supports_image=True,
        thinking_control=thinking_control,
        metadata_source=source,
        supports_tools=True,
        supports_streaming=True,
    )
    write_cached_provider_models(provider, [discovered])
    path = get_settings().data_dir / MODEL_DISCOVERY_CACHE_NAME / f"{provider}.json"
    cached = json.loads(path.read_text())
    assert cached["version"] == 5
    del cached["models"][0]["sharedContextWindowTokens"]
    path.write_text(json.dumps(cached))

    def unexpected_discovery(*_, **__):
        raise AssertionError("Runtime config must resolve without provider discovery.")

    monkeypatch.setattr(model_providers, "_get_json", unexpected_discovery)
    config = _config_from_bundle(
        monkeypatch, provider=provider, model=model, max_tokens=None
    )
    assert config.thinking_control == thinking_control
    assert config.model_max_output_tokens == 64_000
    assert config.shared_context_window_tokens == expected_total
    restored = get_cached_provider_model(provider, model)
    assert (
        restored.supports_image
        and restored.supports_tools
        and restored.supports_streaming
    )
    model_metadata._fetch_catalog.assert_not_called()
    model_metadata._fetch_reasoning_catalog.assert_not_called()


def test_anthropic_current_shared_window_wins_over_larger_public_reference(monkeypatch):
    config = _config_from_bundle(
        monkeypatch,
        provider="anthropic",
        model="claude-sonnet-4-5",
        max_tokens=64_000,
    )
    assert config.context_window_tokens == 200_000
    assert config.shared_context_window_tokens == 200_000
    prompt = LlmPrompt(messages=[{"role": "user", "content": "text " * 144_000}])
    resolved = resolve_request_output_budget(config, prompt)
    assert 0 < resolved.request_max_output_tokens < 20_000
    assert (
        estimate_prompt_tokens(prompt) + resolved.request_max_output_tokens <= 200_000
    )
