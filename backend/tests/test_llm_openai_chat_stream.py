import asyncio
from typing import Any

import pytest
from openai.types.chat import ChatCompletionChunk

from app.services.llm.adapters import openai_chat
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import AgentLlmConfig, LlmStreamEvent


class _Stream:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks
        self.close_count = 0

    def __aiter__(self) -> "_Stream":
        return self

    async def __anext__(self) -> ChatCompletionChunk:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self) -> None:
        self.close_count += 1


class _Client:
    def __init__(self, stream: _Stream) -> None:
        self._stream = stream
        self.close_count = 0
        self.chat = _Chat(self)

    async def close(self) -> None:
        self.close_count += 1


class _Chat:
    def __init__(self, client: _Client) -> None:
        self.completions = _Completions(client)


class _Completions:
    def __init__(self, client: _Client) -> None:
        self._client = client

    async def create(self, **_: Any) -> _Stream:
        return self._client._stream


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="openai-stream-test",
        name="DeepSeek test",
        provider="deepseek",
        model="deepseek-reasoner",
        base_url="https://api.deepseek.test/v1",
        api_key="secret",
        temperature=0,
        top_p=1,
        max_tokens=None,
        timeout_seconds=60,
        supports_streaming=True,
    )


def _chunk(
    delta: dict[str, Any],
    *,
    finish_reason: str | None = None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "chunk-1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "deepseek-reasoner",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "delta": delta,
                },
            ],
        },
    )


def _tool_delta(
    *,
    index: int,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str,
) -> dict[str, Any]:
    function: dict[str, str] = {"arguments": arguments}
    if name is not None:
        function["name"] = name
    tool_call: dict[str, Any] = {"index": index, "function": function}
    if call_id is not None:
        tool_call.update({"id": call_id, "type": "function"})
    return {"tool_calls": [tool_call]}


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up a value",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        },
    ]


def test_openai_chat_does_not_publish_tool_call_before_authoritative_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk(
                _tool_delta(
                    index=0,
                    call_id="call-1",
                    name="lookup",
                    arguments='{"value":1}',
                ),
            ),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    async def scenario() -> list[str]:
        event_types: list[str] = []
        with pytest.raises(LlmRequestError, match="before completion"):
            async for event in openai_chat.stream_tool_call(
                _config(),
                [{"role": "user", "content": "lookup"}],
                _tools(),
            ):
                event_types.append(event.type)
        return event_types

    event_types = asyncio.run(scenario())

    assert event_types == ["activity"]
    assert provider_stream.close_count == 1
    assert client.close_count == 1


def test_openai_chat_does_not_publish_partial_text_after_incomplete_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream([_chunk({"content": "partial"})])
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    async def scenario() -> list[str]:
        event_types: list[str] = []
        with pytest.raises(LlmRequestError, match="before completion"):
            async for event in openai_chat.stream(
                _config(),
                [{"role": "user", "content": "answer"}],
            ):
                event_types.append(event.type)
        return event_types

    event_types = asyncio.run(scenario())

    assert event_types == ["text_delta"]
    assert provider_stream.close_count == 1
    assert client.close_count == 1


def test_openai_chat_length_finish_never_exposes_accumulated_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk(
                _tool_delta(
                    index=0,
                    call_id="call-1",
                    name="lookup",
                    arguments='{"value":1}',
                ),
            ),
            _chunk({}, finish_reason="length"),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    async def scenario() -> list[LlmStreamEvent]:
        return [
            event
            async for event in openai_chat.stream_tool_call(
                _config(),
                [{"role": "user", "content": "lookup"}],
                _tools(),
            )
        ]

    events = asyncio.run(scenario())

    assert [event.type for event in events] == ["activity", "done"]
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.stop_reason == "length"
    assert terminal.tool_calls == []


def test_openai_chat_sdk_accumulator_keeps_interleaved_calls_and_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk({"reasoning_content": "think "}),
            _chunk(
                _tool_delta(
                    index=0,
                    call_id="call-1",
                    name="lookup",
                    arguments='{"val',
                ),
            ),
            _chunk(
                _tool_delta(
                    index=1,
                    call_id="call-2",
                    name="lookup",
                    arguments='{"value":2}',
                ),
            ),
            _chunk(_tool_delta(index=0, arguments='ue":1}')),
            _chunk({}, finish_reason="tool_calls"),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    async def scenario() -> list[LlmStreamEvent]:
        return [
            event
            async for event in openai_chat.stream_tool_call(
                _config(),
                [{"role": "user", "content": "lookup"}],
                _tools(),
            )
        ]

    events = asyncio.run(scenario())

    assert [event.type for event in events] == [
        "reasoning_delta",
        "activity",
        "activity",
        "activity",
        "done",
    ]
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.reasoning == "think"
    assert [call.id for call in terminal.tool_calls] == ["call-1", "call-2"]
    assert [call.arguments for call in terminal.tool_calls] == [
        {"value": 1},
        {"value": 2},
    ]
