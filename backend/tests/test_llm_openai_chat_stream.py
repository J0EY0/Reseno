import asyncio
from typing import Any

import pytest
from openai.types.chat import ChatCompletionChunk

from app.services.llm.adapters import openai_chat
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import AgentLlmConfig, LlmPrompt, LlmStreamEvent


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
        self.create_params: dict[str, Any] = {}
        self.chat = _Chat(self)

    async def close(self) -> None:
        self.close_count += 1


class _Chat:
    def __init__(self, client: _Client) -> None:
        self.completions = _Completions(client)


class _Completions:
    def __init__(self, client: _Client) -> None:
        self._client = client

    async def create(self, **params: Any) -> _Stream:
        self._client.create_params = params
        return self._client._stream


def _config(**overrides: Any) -> AgentLlmConfig:
    values: dict[str, Any] = {
        "client_id": "openai-stream-test",
        "name": "DeepSeek test",
        "provider": "deepseek",
        "model": "deepseek-reasoner",
        "base_url": "https://api.deepseek.test/v1",
        "api_key": "secret",
        "temperature": 0,
        "top_p": 1,
        "max_tokens": None,
        "timeout_seconds": 60,
        "supports_streaming": True,
    }
    values.update(overrides)
    return AgentLlmConfig(**values)


def _chunk(
    delta: dict[str, Any],
    *,
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
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
            "usage": usage,
        },
    )


def _usage_chunk(usage: dict[str, Any]) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "chunk-1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "deepseek-reasoner",
            "choices": [],
            "usage": usage,
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
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
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
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
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
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
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
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
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


def test_official_deepseek_text_stream_reports_cache_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk({"content": "Done"}),
            _chunk({}, finish_reason="stop"),
            _usage_chunk(
                {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                    "prompt_cache_hit_tokens": 8,
                },
            ),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect(
            openai_chat.stream(
                _config(provider_kind="cloud"),
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
            ),
        ),
    )

    assert client.create_params["stream_options"] == {"include_usage": True}
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.usage is not None
    assert terminal.usage.input_tokens == 12
    assert terminal.usage.cached_input_tokens == 8
    assert terminal.usage.total_tokens == 15


def test_official_qwen_text_stream_reports_cache_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk({"content": "Done"}),
            _chunk({}, finish_reason="stop"),
            _usage_chunk(
                {
                    "prompt_tokens": 11,
                    "completion_tokens": 2,
                    "total_tokens": 13,
                    "prompt_tokens_details": {"cached_tokens": 7},
                },
            ),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect(
            openai_chat.stream(
                _config(provider="qwen", provider_kind="cloud"),
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
            ),
        ),
    )

    assert client.create_params["stream_options"] == {"include_usage": True}
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.usage is not None
    assert terminal.usage.cached_input_tokens == 7


def test_official_minimax_text_stream_reports_cache_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk({"content": "Done"}),
            _chunk({}, finish_reason="stop"),
            _usage_chunk(
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "prompt_tokens_details": {"cached_tokens": 6},
                },
            ),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect(
            openai_chat.stream(
                _config(provider="minimax", provider_kind="cloud"),
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
            ),
        ),
    )

    assert client.create_params["stream_options"] == {"include_usage": True}
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.usage is not None
    assert terminal.usage.cached_input_tokens == 6


def test_official_moonshot_text_stream_reports_terminal_cache_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk({"content": "Done"}),
            _chunk(
                {},
                finish_reason="stop",
                usage={
                    "prompt_tokens": 9,
                    "completion_tokens": 2,
                    "total_tokens": 11,
                    "cached_tokens": 5,
                },
            ),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect(
            openai_chat.stream(
                _config(provider="moonshot", provider_kind="cloud"),
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
            ),
        ),
    )

    assert client.create_params["stream_options"] == {"include_usage": True}
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.usage is not None
    assert terminal.usage.cached_input_tokens == 5


def test_official_glm_text_stream_uses_terminal_usage_without_stream_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk({"content": "Done"}),
            _chunk(
                {},
                finish_reason="stop",
                usage={
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "total_tokens": 10,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            ),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect(
            openai_chat.stream(
                _config(provider="glm", provider_kind="cloud"),
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
            ),
        ),
    )

    assert "stream_options" not in client.create_params
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.usage is not None
    assert terminal.usage.cached_input_tokens == 4


def test_custom_text_stream_does_not_receive_stream_usage_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream([_chunk({}, finish_reason="stop")])
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    asyncio.run(
        _collect(
            openai_chat.stream(
                _config(provider="custom-cloud", provider_kind="custom"),
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
            ),
        ),
    )

    assert "stream_options" not in client.create_params


@pytest.mark.parametrize("provider", ["ollama", "vllm", "sglang"])
def test_registered_local_text_stream_requests_usage(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    provider_stream = _Stream([_chunk({}, finish_reason="stop")])
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    asyncio.run(
        _collect(
            openai_chat.stream(
                _config(provider=provider, provider_kind="local"),
                LlmPrompt(messages=[{"role": "user", "content": "answer"}]),
            ),
        ),
    )

    assert client.create_params["stream_options"] == {"include_usage": True}


def test_official_deepseek_tool_stream_reports_cache_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream(
        [
            _chunk(
                _tool_delta(
                    index=0,
                    call_id="call-cache",
                    name="lookup",
                    arguments='{"value":1}',
                ),
            ),
            _chunk({}, finish_reason="tool_calls"),
            _usage_chunk(
                {
                    "prompt_tokens": 14,
                    "completion_tokens": 2,
                    "total_tokens": 16,
                    "prompt_cache_hit_tokens": 9,
                },
            ),
        ],
    )
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect(
            openai_chat.stream_tool_call(
                _config(provider_kind="cloud"),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            ),
        ),
    )

    assert client.create_params["stream_options"] == {"include_usage": True}
    terminal = events[-1].message
    assert terminal is not None
    assert terminal.usage is not None
    assert terminal.usage.cached_input_tokens == 9
    assert terminal.usage.total_tokens == 16


def test_custom_tool_stream_does_not_receive_stream_usage_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_stream = _Stream([_chunk({}, finish_reason="stop")])
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    asyncio.run(
        _collect(
            openai_chat.stream_tool_call(
                _config(provider="custom-cloud", provider_kind="custom"),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            ),
        ),
    )

    assert "stream_options" not in client.create_params


@pytest.mark.parametrize("provider", ["ollama", "vllm", "sglang"])
def test_registered_local_tool_stream_requests_usage(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    provider_stream = _Stream([_chunk({}, finish_reason="stop")])
    client = _Client(provider_stream)
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    asyncio.run(
        _collect(
            openai_chat.stream_tool_call(
                _config(provider=provider, provider_kind="local"),
                LlmPrompt(messages=[{"role": "user", "content": "lookup"}]),
                _tools(),
            ),
        ),
    )

    assert client.create_params["stream_options"] == {"include_usage": True}


async def _collect(stream: Any) -> list[LlmStreamEvent]:
    return [event async for event in stream]
