import asyncio
from types import ModuleType
from typing import Any

import pytest

from app.services.llm import dispatch
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
    openai_chat,
    openai_responses,
)
from app.services.llm.types import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmStreamEvent,
    LlmToolCall,
)

PROVIDERS: tuple[tuple[str, ModuleType], ...] = (
    ("openai_compatible_chat", openai_chat),
    ("openai_responses", openai_responses),
    ("anthropic_messages", anthropic_messages),
    ("google_gemini", google_gemini),
)


def _config(api_family: str, *, supports_streaming: bool) -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id=f"dispatch-{api_family}",
        name="Dispatch test",
        provider="test",
        model="test-model",
        base_url="https://provider.test/v1",
        api_key="secret",
        temperature=0,
        top_p=1,
        max_tokens=None,
        timeout_seconds=60,
        api_family=api_family,
        supports_streaming=supports_streaming,
    )


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up a value",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def _terminal_message() -> LlmAssistantMessage:
    return LlmAssistantMessage(
        tool_calls=[
            LlmToolCall(
                id="call-lookup",
                name="lookup",
                arguments={"query": "resume"},
                raw_arguments='{"query":"resume"}',
            ),
        ],
        stop_reason="tool_calls",
    )


@pytest.mark.parametrize(("api_family", "adapter"), PROVIDERS)
def test_streaming_provider_uses_private_tool_activity_stream(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    stream_calls = 0

    async def fake_stream_tool_call(*_: object):
        nonlocal stream_calls
        stream_calls += 1
        yield LlmStreamEvent(type="activity")
        yield LlmStreamEvent(type="done", message=_terminal_message())

    async def forbidden_unary(*_: object) -> LlmAssistantMessage:
        raise AssertionError("streaming providers must not use unary tool calls")

    monkeypatch.setattr(adapter, "stream_tool_call", fake_stream_tool_call)
    monkeypatch.setattr(adapter, "complete_tool_call", forbidden_unary)

    message = asyncio.run(
        dispatch.async_complete_tool_call(
            _config(api_family, supports_streaming=True),
            [{"role": "user", "content": "lookup"}],
            _tools(),
        ),
    )

    assert stream_calls == 1
    assert [call.name for call in message.tool_calls] == ["lookup"]


@pytest.mark.parametrize(("api_family", "adapter"), PROVIDERS)
def test_non_streaming_provider_uses_complete_response_without_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    complete_calls = 0

    async def fake_complete_tool_call(*_: object) -> LlmAssistantMessage:
        nonlocal complete_calls
        complete_calls += 1
        return _terminal_message()

    def forbidden_stream(*_: object):
        raise AssertionError("non-streaming providers must not open a stream")

    monkeypatch.setattr(adapter, "complete_tool_call", fake_complete_tool_call)
    monkeypatch.setattr(adapter, "stream_tool_call", forbidden_stream)

    message = asyncio.run(
        dispatch.async_complete_tool_call(
            _config(api_family, supports_streaming=False),
            [{"role": "user", "content": "lookup"}],
            _tools(),
        ),
    )

    assert complete_calls == 1
    assert [call.name for call in message.tool_calls] == ["lookup"]
