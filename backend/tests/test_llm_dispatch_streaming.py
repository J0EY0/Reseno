import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
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
    LlmPrompt,
    LlmRequestContext,
    LlmStreamEvent,
    LlmToolCall,
)
from app.services.llm.validation import validate_tool_calls

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


async def _collect_events(
    events: AsyncIterator[LlmStreamEvent],
) -> list[LlmStreamEvent]:
    return [event async for event in events]


@pytest.mark.parametrize(("api_family", "adapter"), PROVIDERS)
def test_streaming_provider_uses_private_tool_activity_stream(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    stream_calls = 0

    async def fake_stream_tool_call(*_: object, **__: object):
        nonlocal stream_calls
        stream_calls += 1
        yield LlmStreamEvent(type="activity")
        yield LlmStreamEvent(type="done", message=_terminal_message())

    async def forbidden_unary(*_: object, **__: object) -> LlmAssistantMessage:
        raise AssertionError("streaming providers must not use unary tool calls")

    monkeypatch.setattr(adapter, "stream_tool_call", fake_stream_tool_call)
    monkeypatch.setattr(adapter, "complete_tool_call", forbidden_unary)

    message_events = asyncio.run(
        _collect_events(
            dispatch.async_stream_tool_call(
                _config(api_family, supports_streaming=True),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            )
        ),
    )
    assert message_events[-1].type == "done"
    message = message_events[-1].message
    assert message is not None

    assert stream_calls == 1
    assert [call.name for call in message.tool_calls] == ["lookup"]


@pytest.mark.parametrize(("api_family", "adapter"), PROVIDERS)
def test_streaming_tool_dispatch_forwards_events_and_validates_done(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    forwarded = [
        LlmStreamEvent(type="text_delta", delta="Checking"),
        LlmStreamEvent(type="reasoning_delta", delta="Private reasoning"),
        LlmStreamEvent(type="activity"),
    ]
    invalid_call = LlmToolCall(
        id="call-invalid",
        name="lookup",
        arguments={},
        raw_arguments="{}",
    )

    async def fake_stream_tool_call(*_: object, **__: object):
        for event in forwarded:
            yield event
        yield LlmStreamEvent(
            type="done",
            message=LlmAssistantMessage(
                content="Checking",
                tool_calls=[invalid_call],
                stop_reason="tool_calls",
            ),
        )

    monkeypatch.setattr(adapter, "stream_tool_call", fake_stream_tool_call)

    events = asyncio.run(
        _collect_events(
            dispatch.async_stream_tool_call(
                _config(api_family, supports_streaming=True),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            ),
        ),
    )

    assert events[:3] == forwarded
    assert all(
        actual is expected for actual, expected in zip(events, forwarded, strict=False)
    )
    terminal = events[3].message
    assert terminal is not None
    assert terminal.tool_calls == [invalid_call]
    assert len(terminal.validation_errors) == 1
    assert terminal.validation_errors[0].tool_call is invalid_call


@pytest.mark.parametrize(("api_family", "adapter"), PROVIDERS)
def test_non_streaming_provider_uses_complete_response_without_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    complete_calls = 0

    async def fake_complete_tool_call(
        *_: object,
        **__: object,
    ) -> LlmAssistantMessage:
        nonlocal complete_calls
        complete_calls += 1
        return _terminal_message()

    def forbidden_stream(*_: object, **__: object):
        raise AssertionError("non-streaming providers must not open a stream")

    monkeypatch.setattr(adapter, "complete_tool_call", fake_complete_tool_call)
    monkeypatch.setattr(adapter, "stream_tool_call", forbidden_stream)

    message_events = asyncio.run(
        _collect_events(
            dispatch.async_stream_tool_call(
                _config(api_family, supports_streaming=False),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            )
        ),
    )
    assert message_events[-1].type == "done"
    message = message_events[-1].message
    assert message is not None

    assert complete_calls == 1
    assert [call.name for call in message.tool_calls] == ["lookup"]


@pytest.mark.parametrize(("api_family", "adapter"), PROVIDERS)
def test_non_streaming_tool_dispatch_synthesizes_text_and_done(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    terminal_message = replace(_terminal_message(), content="Completed")

    async def fake_complete_tool_call(
        *_: object,
        **__: object,
    ) -> LlmAssistantMessage:
        return terminal_message

    def forbidden_stream(*_: object, **__: object):
        raise AssertionError("non-streaming providers must not open a stream")

    monkeypatch.setattr(adapter, "complete_tool_call", fake_complete_tool_call)
    monkeypatch.setattr(adapter, "stream_tool_call", forbidden_stream)

    events = asyncio.run(
        _collect_events(
            dispatch.async_stream_tool_call(
                _config(api_family, supports_streaming=False),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            ),
        ),
    )

    assert [event.type for event in events] == ["text_delta", "done"]
    assert events[0].delta == "Completed"
    assert events[1].message is not None
    assert [call.name for call in events[1].message.tool_calls] == ["lookup"]


def test_dispatch_validates_union_arguments_against_provider_projection() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "edit",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "payload": {
                            "oneOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "mode": {"const": "insert"},
                                        "title": {"type": "string"},
                                    },
                                    "required": ["mode", "title"],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "mode": {"const": "update"},
                                        "patch": {"type": "string"},
                                    },
                                    "required": ["mode", "patch"],
                                },
                            ],
                        },
                    },
                    "required": ["payload"],
                },
            },
        },
    ]
    call = LlmToolCall(
        id="call-edit",
        name="edit",
        arguments={"payload": {"mode": "insert"}},
        raw_arguments='{"payload":{"mode":"insert"}}',
    )

    strict_calls, strict_errors = validate_tool_calls([call], tools)
    message = dispatch._validated_tool_message(
        LlmAssistantMessage(tool_calls=[call], stop_reason="tool_calls"),
        tools,
    )

    assert strict_calls == []
    assert len(strict_errors) == 1
    assert message.tool_calls == [call]
    assert message.validation_errors == []


@pytest.mark.parametrize(
    ("case", "error_pattern"),
    [
        ("missing_done", "ended before completion"),
        ("empty_done", "empty response"),
        ("after_done", "events after completion"),
    ],
)
def test_streaming_tool_dispatch_preserves_terminal_errors(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    error_pattern: str,
) -> None:
    async def fake_stream_tool_call(*_: object, **__: object):
        if case == "missing_done":
            yield LlmStreamEvent(type="activity")
            return
        if case == "empty_done":
            yield LlmStreamEvent(type="done")
            return
        yield LlmStreamEvent(type="done", message=_terminal_message())
        yield LlmStreamEvent(type="activity")

    monkeypatch.setattr(openai_chat, "stream_tool_call", fake_stream_tool_call)

    with pytest.raises(dispatch.LlmRequestError, match=error_pattern):
        asyncio.run(
            _collect_events(
                dispatch.async_stream_tool_call(
                    _config("openai_compatible_chat", supports_streaming=True),
                    LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                    _tools(),
                ),
            ),
        )


@pytest.mark.parametrize(
    ("api_family", "adapter"),
    [
        ("openai_compatible_chat", openai_chat),
        ("openai_responses", openai_responses),
    ],
)
def test_streaming_openai_dispatch_forwards_request_context(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    received_context: LlmRequestContext | None = None

    async def fake_stream_tool_call(
        *_: object,
        request_context: LlmRequestContext | None = None,
    ):
        nonlocal received_context
        received_context = request_context
        yield LlmStreamEvent(type="done", message=_terminal_message())

    monkeypatch.setattr(adapter, "stream_tool_call", fake_stream_tool_call)
    request_context = LlmRequestContext(cache_key="resume-session-1")

    asyncio.run(
        _collect_events(
            dispatch.async_stream_tool_call(
                replace(
                    _config(api_family, supports_streaming=True),
                    provider="openai",
                ),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
                request_context=request_context,
            )
        ),
    )

    assert received_context is request_context


def test_dispatch_rejects_duplicate_tool_call_ids_without_losing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [
        LlmToolCall(
            id="call-duplicate",
            name="lookup",
            arguments={"query": "first"},
            raw_arguments='{"query":"first"}',
        ),
        LlmToolCall(
            id="call-duplicate",
            name="lookup",
            arguments={"query": "second"},
            raw_arguments='{"query":"second"}',
        ),
    ]

    async def fake_complete_tool_call(
        *_: object,
        **__: object,
    ) -> LlmAssistantMessage:
        return LlmAssistantMessage(tool_calls=calls, stop_reason="tool_calls")

    monkeypatch.setattr(openai_chat, "complete_tool_call", fake_complete_tool_call)

    message_events = asyncio.run(
        _collect_events(
            dispatch.async_stream_tool_call(
                _config("openai_compatible_chat", supports_streaming=False),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            )
        ),
    )
    assert message_events[-1].type == "done"
    message = message_events[-1].message
    assert message is not None

    assert message.tool_calls == calls
    assert len(message.validation_errors) == 2
    assert message.validation_errors[0].tool_call is calls[0]
    assert message.validation_errors[1].tool_call is calls[1]
    assert all("unique" in error.message.lower() for error in message.validation_errors)


@pytest.mark.parametrize("call_id", ["", "   "])
def test_dispatch_rejects_blank_tool_call_id(
    monkeypatch: pytest.MonkeyPatch,
    call_id: str,
) -> None:
    call = LlmToolCall(
        id=call_id,
        name="lookup",
        arguments={"query": "resume"},
        raw_arguments='{"query":"resume"}',
    )

    async def fake_complete_tool_call(
        *_: object,
        **__: object,
    ) -> LlmAssistantMessage:
        return LlmAssistantMessage(tool_calls=[call], stop_reason="tool_calls")

    monkeypatch.setattr(openai_chat, "complete_tool_call", fake_complete_tool_call)

    message_events = asyncio.run(
        _collect_events(
            dispatch.async_stream_tool_call(
                _config("openai_compatible_chat", supports_streaming=False),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            )
        ),
    )
    assert message_events[-1].type == "done"
    message = message_events[-1].message
    assert message is not None

    assert message.tool_calls == [call]
    assert len(message.validation_errors) == 1
    assert message.validation_errors[0].tool_call is call
    assert "non-empty" in message.validation_errors[0].message
