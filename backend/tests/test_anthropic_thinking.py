from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services.llm import (
    AgentLlmConfig,
    LlmPrompt,
    LlmRequestError,
    async_complete_chat,
    async_complete_tool_call,
)
from app.services.llm.adapters import anthropic_messages
from app.services.thinking import ThinkingControl


def _config(
    *,
    thinking_control: ThinkingControl,
    max_tokens: int = 32_000,
) -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="anthropic-thinking-test",
        name="Claude Test",
        provider="anthropic",
        provider_kind="cloud",
        model="claude-discovered-test",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-test-secret",
        temperature=0.3,
        top_p=0.8,
        max_tokens=max_tokens,
        timeout_seconds=12,
        api_family="anthropic_messages",
        supports_streaming=False,
        thinking_control=thinking_control,
    )


def _tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "resume_lookup",
            "description": "Read the current resume",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


def test_anthropic_native_auto_uses_adaptive_without_effort_or_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-adaptive-thinking",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_chat(
            _config(thinking_control="native_auto"),
            LlmPrompt(messages=[{"role": "user", "content": "Review."}]),
        ),
    )

    payload = captured["payload"]
    assert payload["thinking"] == {"type": "adaptive"}
    assert "output_config" not in payload
    assert "temperature" not in payload
    assert "top_p" not in payload


@pytest.mark.parametrize(
    ("max_tokens", "expected_thinking_budget"),
    [
        (1_025, 1_024),
        (6_000, 3_000),
        (100_000, 16_000),
    ],
)
def test_anthropic_native_budget_derives_a_bounded_legacy_thinking_budget(
    monkeypatch: pytest.MonkeyPatch,
    max_tokens: int,
    expected_thinking_budget: int,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-legacy-thinking",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_chat(
            _config(
                thinking_control="native_budget",
                max_tokens=max_tokens,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "Review."}]),
        ),
    )

    payload = captured["payload"]
    assert payload["max_tokens"] == max_tokens
    assert payload["thinking"] == {
        "type": "enabled",
        "budget_tokens": expected_thinking_budget,
    }
    assert "output_config" not in payload
    assert "temperature" not in payload
    assert "top_p" not in payload


def test_anthropic_native_budget_rejects_output_too_small_for_official_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    with pytest.raises(
        LlmRequestError,
        match="legacy thinking requires max_tokens greater than 1024",
    ):
        asyncio.run(
            async_complete_chat(
                _config(
                    thinking_control="native_budget",
                    max_tokens=1_024,
                ),
                LlmPrompt(messages=[{"role": "user", "content": "Review."}]),
            ),
        )

    assert called is False


@pytest.mark.parametrize("thinking_control", ["none", "provider_default"])
def test_anthropic_none_and_provider_default_omit_explicit_thinking(
    monkeypatch: pytest.MonkeyPatch,
    thinking_control: ThinkingControl,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-default-thinking",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_chat(
            _config(thinking_control=thinking_control),
            LlmPrompt(messages=[{"role": "user", "content": "Review."}]),
        ),
    )

    payload = captured["payload"]
    assert "thinking" not in payload
    assert payload["temperature"] == 0.3
    assert payload["top_p"] == 0.8


def test_anthropic_registers_tools_without_redundant_auto_tool_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-tool-registration",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "No tool needed."}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_tool_call(
            _config(thinking_control="native_auto"),
            LlmPrompt(messages=[{"role": "user", "content": "Review."}]),
            [_tool()],
        ),
    )

    payload = captured["payload"]
    assert payload["tools"][0]["name"] == "resume_lookup"
    assert "tool_choice" not in payload
