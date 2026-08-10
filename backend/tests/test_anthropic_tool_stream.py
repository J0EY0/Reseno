from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.services.llm.adapters import anthropic_messages
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import AgentLlmConfig, LlmStreamEvent


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="anthropic-stream-test",
        name="Claude Test",
        provider="anthropic",
        model="claude-test",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-test-secret",
        temperature=None,
        top_p=None,
        max_tokens=256,
        timeout_seconds=12,
        api_family="anthropic_messages",
    )


def _tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "resume_lookup",
            "description": "Lookup resume content",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


async def _collect(events: AsyncIterator[LlmStreamEvent]) -> list[LlmStreamEvent]:
    return [event async for event in events]


class _ClosableEventStream:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = iter(events)
        self.close_count = 0

    def __aiter__(self) -> _ClosableEventStream:
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.close_count += 1


class _BlockingEventStream:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.close_count = 0

    def __aiter__(self) -> _BlockingEventStream:
        return self

    async def __anext__(self) -> dict[str, Any]:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        self.close_count += 1


def test_anthropic_tool_stream_assembles_arguments_only_after_message_stop(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_stream_json(
        url: str,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        captured["url"] = url
        captured.update(kwargs)
        for event in [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-tool-stream",
                    "usage": {"input_tokens": 7},
                },
            },
            {"type": "ping"},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-stream",
                    "name": "resume_lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": ""},
            },
            {"type": "message_delta", "delta": {}, "usage": {}},
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":',
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '"project"}',
                },
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 5},
            },
            {"type": "message_stop"},
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect(
            anthropic_messages.stream_tool_call(
                _config(),
                [{"role": "user", "content": "Find my project."}],
                [_tool()],
            ),
        ),
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["tools"][0]["eager_input_streaming"] is True
    assert [event.type for event in events] == [
        "activity",
        "activity",
        "activity",
        "activity",
        "activity",
        "activity",
        "done",
    ]
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.response_id == "msg-tool-stream"
    assert terminal.stop_reason == "tool_calls"
    assert terminal.usage and terminal.usage.total_tokens == 12
    assert terminal.tool_calls[0].id == "toolu-stream"
    assert terminal.tool_calls[0].name == "resume_lookup"
    assert terminal.tool_calls[0].arguments == {"query": "project"}
    assert terminal.tool_calls[0].raw_arguments == '{"query":"project"}'


def test_anthropic_tool_stream_preserves_text_thinking_and_signature(
    monkeypatch,
) -> None:
    async def fake_stream_json(
        _url: str,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        for event in [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-thinking-tool",
                    "usage": {"input_tokens": 10},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "Inspect first."},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "signed-state"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Checking."},
            },
            {"type": "content_block_stop", "index": 1},
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-thinking",
                    "name": "resume_lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":"experience"}',
                },
            },
            {"type": "content_block_stop", "index": 2},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 8},
            },
            {"type": "message_stop"},
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect(
            anthropic_messages.stream_tool_call(
                _config(),
                [{"role": "user", "content": "Inspect experience."}],
                [_tool()],
            ),
        ),
    )

    assert [(event.type, event.delta) for event in events[:-1]] == [
        ("activity", ""),
        ("reasoning_delta", "Inspect first."),
        ("activity", ""),
        ("text_delta", "Checking."),
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
    ]
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.content == "Checking."
    assert terminal.reasoning == "Inspect first."
    assert terminal.provider_state == {
        "thinking_blocks": [
            {
                "type": "thinking",
                "thinking": "Inspect first.",
                "signature": "signed-state",
            },
        ],
    }
    assert terminal.usage and terminal.usage.total_tokens == 18


def test_anthropic_tool_stream_rejects_a_terminal_reason_that_contradicts_tool_use(
    monkeypatch,
) -> None:
    async def fake_stream_json(
        _url: str,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        for event in [
            {
                "type": "message_start",
                "message": {"id": "msg-invalid-terminal"},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-invalid-terminal",
                    "name": "resume_lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":"skills"}',
                },
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
            },
            {"type": "message_stop"},
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="invalid stream completion"):
        asyncio.run(
            _collect(
                anthropic_messages.stream_tool_call(
                    _config(),
                    [{"role": "user", "content": "Find skills."}],
                    [_tool()],
                ),
            ),
        )


def test_anthropic_tool_stream_rejects_eof_before_message_stop(monkeypatch) -> None:
    async def fake_stream_json(
        _url: str,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        for event in [
            {
                "type": "message_start",
                "message": {"id": "msg-truncated"},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-truncated",
                    "name": "resume_lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":"unfinished',
                },
            },
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="ended before completion"):
        asyncio.run(
            _collect(
                anthropic_messages.stream_tool_call(
                    _config(),
                    [{"role": "user", "content": "Find skills."}],
                    [_tool()],
                ),
            ),
        )


def test_anthropic_tool_stream_never_exposes_a_max_tokens_tool_fragment(
    monkeypatch,
) -> None:
    async def fake_stream_json(
        _url: str,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        for event in [
            {
                "type": "message_start",
                "message": {"id": "msg-max-tokens"},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-max-tokens",
                    "name": "resume_lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":"unfinished',
                },
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "max_tokens"},
            },
            {"type": "message_stop"},
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect(
            anthropic_messages.stream_tool_call(
                _config(),
                [{"role": "user", "content": "Find skills."}],
                [_tool()],
            ),
        ),
    )

    terminal = events[-1].message
    assert terminal is not None
    assert terminal.stop_reason == "length"
    assert terminal.tool_calls == []


def test_anthropic_tool_stream_closes_provider_when_consumer_stops(
    monkeypatch,
) -> None:
    provider_stream = _ClosableEventStream(
        [
            {
                "type": "message_start",
                "message": {"id": "msg-consumer-stop"},
            },
            {"type": "ping"},
        ],
    )
    monkeypatch.setattr(
        anthropic_messages,
        "async_stream_json",
        lambda *_args, **_kwargs: provider_stream,
    )

    async def consume_one_event() -> LlmStreamEvent:
        stream = anthropic_messages.stream_tool_call(
            _config(),
            [{"role": "user", "content": "Find skills."}],
            [_tool()],
        )
        event = await anext(stream)
        await stream.aclose()
        return event

    first_event = asyncio.run(consume_one_event())

    assert first_event.type == "activity"
    assert provider_stream.close_count == 1


def test_anthropic_tool_stream_closes_provider_when_cancelled(monkeypatch) -> None:
    provider_stream = _BlockingEventStream()
    monkeypatch.setattr(
        anthropic_messages,
        "async_stream_json",
        lambda *_args, **_kwargs: provider_stream,
    )

    async def cancel_pending_read() -> None:
        stream = anthropic_messages.stream_tool_call(
            _config(),
            [{"role": "user", "content": "Find skills."}],
            [_tool()],
        )
        pending_read = asyncio.create_task(anext(stream))
        await provider_stream.started.wait()
        pending_read.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending_read

    asyncio.run(cancel_pending_read())

    assert provider_stream.close_count == 1


def test_anthropic_chat_stream_also_requires_message_stop(monkeypatch) -> None:
    async def fake_stream_json(
        _url: str,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        for event in [
            {
                "type": "message_start",
                "message": {"id": "msg-chat-truncated"},
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Partial"},
            },
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="ended before completion"):
        asyncio.run(
            _collect(
                anthropic_messages.stream(
                    _config(),
                    [{"role": "user", "content": "Hello."}],
                ),
            ),
        )


def test_anthropic_tool_stream_keeps_stop_reason_across_usage_only_deltas(
    monkeypatch,
) -> None:
    async def fake_stream_json(
        _url: str,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        for event in [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-multi-delta",
                    "usage": {"input_tokens": 3},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-multi-delta",
                    "name": "resume_lookup",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"query":"skills"}',
                },
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 4},
            },
            {
                "type": "message_delta",
                "delta": {},
                "usage": {"output_tokens": 5},
            },
            {"type": "message_stop"},
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect(
            anthropic_messages.stream_tool_call(
                _config(),
                [{"role": "user", "content": "Find skills."}],
                [_tool()],
            ),
        ),
    )

    terminal = events[-1].message
    assert terminal is not None
    assert terminal.stop_reason == "tool_calls"
    assert terminal.usage and terminal.usage.total_tokens == 8
