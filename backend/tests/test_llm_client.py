import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIStatusError
from openai.types.chat import ChatCompletionChunk

from app.services.llm import (
    AgentLlmConfig,
    LlmRequestError,
    async_complete_chat,
    async_complete_tool_call,
    async_stream_chat,
    common,
)
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
    openai_chat,
    openai_responses,
)


class AsyncStream:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks
        self.close_count = 0

    def __aiter__(self) -> "AsyncStream":
        return self

    async def __anext__(self) -> object:
        if not self._chunks:
            raise StopAsyncIteration

        return self._chunks.pop(0)

    async def close(self) -> None:
        self.close_count += 1


def _config(**overrides: Any) -> AgentLlmConfig:
    values = {
        "client_id": "llm-test",
        "name": "Test Model",
        "provider": "openai",
        "model": "gpt-test",
        "base_url": "https://api.example.test/v1",
        "api_key": "sk-test-secret",
        "temperature": 0.3,
        "top_p": 0.8,
        "max_tokens": None,
        "timeout_seconds": 12,
        "supports_streaming": False,
    }
    values.update(overrides)
    return AgentLlmConfig(**values)


def test_openai_chat_async_completion_uses_sdk_params(monkeypatch) -> None:
    class FakeChatCompletions:
        create_params: dict[str, Any] = {}

        async def create(self, **kwargs: Any) -> object:
            FakeChatCompletions.create_params = kwargs
            return SimpleNamespace(
                id="chatcmpl-1",
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=4,
                    total_tokens=14,
                ),
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="  SDK response  "),
                    ),
                ],
            )

    class FakeAsyncOpenAI:
        init_kwargs: dict[str, Any] = {}

        def __init__(self, **kwargs: Any) -> None:
            FakeAsyncOpenAI.init_kwargs = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=FakeChatCompletions().create),
            )

    monkeypatch.setattr(common, "AsyncOpenAI", FakeAsyncOpenAI)
    config = _config(
        base_url="https://api.example.test/v1/chat/completions",
        max_tokens=256,
    )

    message = asyncio.run(
        async_complete_chat(config, [{"role": "user", "content": "hello"}]),
    )

    assert message.content == "SDK response"
    assert message.stop_reason == "stop"
    assert message.usage and message.usage.total_tokens == 14
    assert FakeAsyncOpenAI.init_kwargs["api_key"] == "sk-test-secret"
    assert FakeAsyncOpenAI.init_kwargs["base_url"] == "https://api.example.test/v1"
    timeout = FakeAsyncOpenAI.init_kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 30
    assert timeout.read == 12
    assert FakeChatCompletions.create_params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.3,
        "top_p": 0.8,
        "stream": False,
        "max_tokens": 256,
    }


def test_openai_chat_closes_request_client_after_completion(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **_: Any) -> object:
            return SimpleNamespace(
                id="chatcmpl-close",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="closed"),
                    ),
                ],
            )

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    message = asyncio.run(
        openai_chat.complete(
            _config(),
            [{"role": "user", "content": "hello"}],
        ),
    )

    assert message.content == "closed"
    assert client.close_count == 1


def test_openai_chat_closes_request_client_when_create_raises(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **_: Any) -> object:
            raise RuntimeError("provider create failed")

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    with pytest.raises(RuntimeError, match="provider create failed"):
        asyncio.run(
            async_complete_chat(
                _config(),
                [{"role": "user", "content": "hello"}],
            ),
        )

    assert client.close_count == 1


def test_openai_responses_closes_request_client_after_stream(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> AsyncStream:
            return AsyncStream(
                [
                    SimpleNamespace(
                        type="response.completed",
                        response=SimpleNamespace(
                            id="response-close",
                            output_text="closed",
                            output=[],
                            status="completed",
                            usage=None,
                        ),
                    ),
                ],
            )

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    events = asyncio.run(
        _collect_stream(
            openai_responses.stream(
                _config(api_family="openai_responses"),
                [{"role": "user", "content": "hello"}],
            ),
        ),
    )

    assert events[-1].message and events[-1].message.content == "closed"
    assert client.close_count == 1


def test_openai_responses_closes_request_client_when_completion_fails(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> object:
            return SimpleNamespace(
                id="response-empty",
                output_text="",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    with pytest.raises(LlmRequestError, match="empty response"):
        asyncio.run(
            async_complete_chat(
                _config(api_family="openai_responses"),
                [{"role": "user", "content": "hello"}],
            ),
        )

    assert client.close_count == 1


def test_openai_chat_tool_fallback_reuses_and_closes_one_client(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.close_count = 0
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **params: Any) -> object:
            self.calls.append(params)
            if len(self.calls) == 1:
                request = httpx.Request("POST", "https://api.example.test/v1")
                response = httpx.Response(
                    400,
                    request=request,
                    text='{"error":"parallel_tool_calls is unsupported"}',
                )
                raise APIStatusError(
                    "Unsupported parameter",
                    response=response,
                    body=None,
                )
            return SimpleNamespace(
                id="chatcmpl-fallback",
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(content="", tool_calls=[]),
                    ),
                ],
            )

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    message = asyncio.run(
        openai_chat.complete_tool_call(
            _config(),
            [{"role": "user", "content": "inspect"}],
            [],
        ),
    )

    assert message.stop_reason == "tool_calls"
    assert len(client.calls) == 2
    assert client.calls[0]["parallel_tool_calls"] is False
    assert "parallel_tool_calls" not in client.calls[1]
    assert client.close_count == 1


def test_openai_chat_stream_returns_delta_and_done_message(monkeypatch) -> None:
    class FakeChatCompletions:
        async def create(self, **kwargs: Any) -> object:
            assert kwargs["stream"] is True
            return AsyncStream(
                [
                    SimpleNamespace(
                        id="chunk-1",
                        choices=[
                            SimpleNamespace(
                                finish_reason=None,
                                delta=SimpleNamespace(reasoning_content="think "),
                            ),
                        ],
                    ),
                    SimpleNamespace(
                        id="chunk-1",
                        choices=[
                            SimpleNamespace(
                                finish_reason=None,
                                delta=SimpleNamespace(content="streamed"),
                            ),
                        ],
                    ),
                    SimpleNamespace(
                        id="chunk-1",
                        choices=[
                            SimpleNamespace(
                                finish_reason="stop",
                                delta=SimpleNamespace(),
                            ),
                        ],
                    ),
                ],
            )

    class FakeAsyncOpenAI:
        def __init__(self, **_: Any) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=FakeChatCompletions().create),
            )

    monkeypatch.setattr(common, "AsyncOpenAI", FakeAsyncOpenAI)

    events = asyncio.run(
        _collect_stream(
            async_stream_chat(_config(), [{"role": "user", "content": "hi"}]),
        ),
    )

    assert [(event.type, event.delta) for event in events[:-1]] == [
        ("reasoning_delta", "think "),
        ("text_delta", "streamed"),
    ]
    assert events[-1].type == "done"
    assert events[-1].message
    assert events[-1].message.content == "streamed"
    assert events[-1].message.reasoning == "think"


def test_openai_chat_streams_tool_activity_before_complete_validated_call(
    monkeypatch,
) -> None:
    class FakeChatCompletions:
        async def create(self, **kwargs: Any) -> object:
            assert kwargs["stream"] is True
            assert kwargs["tool_choice"] == "auto"
            return AsyncStream(
                [
                    ChatCompletionChunk.model_validate(chunk)
                    for chunk in [
                        {
                            "id": "chunk-tool",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "deepseek-v4-flash",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": None,
                                    "delta": {"reasoning_content": "think "},
                                },
                            ],
                        },
                        {
                            "id": "chunk-tool",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "deepseek-v4-flash",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": None,
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": "call-edit",
                                                "type": "function",
                                                "function": {
                                                    "name": "edit_execute",
                                                    "arguments": '{"edits":',
                                                },
                                            },
                                        ],
                                    },
                                },
                            ],
                        },
                        {
                            "id": "chunk-tool",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "deepseek-v4-flash",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": None,
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "function": {"arguments": "[]}"},
                                            },
                                        ],
                                    },
                                },
                            ],
                        },
                        {
                            "id": "chunk-tool",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "deepseek-v4-flash",
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": "tool_calls",
                                    "delta": {},
                                },
                            ],
                        },
                    ]
                ],
            )

    class FakeAsyncOpenAI:
        def __init__(self, **_: Any) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=FakeChatCompletions().create),
            )

    monkeypatch.setattr(common, "AsyncOpenAI", FakeAsyncOpenAI)

    events = asyncio.run(
        _collect_stream(
            openai_chat.stream_tool_call(
                _config(),
                [{"role": "user", "content": "edit"}],
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "edit_execute",
                            "description": "Execute edits",
                            "parameters": {
                                "type": "object",
                                "properties": {"edits": {"type": "array"}},
                                "required": ["edits"],
                                "additionalProperties": False,
                            },
                        },
                    },
                ],
            ),
        ),
    )

    assert [event.type for event in events] == [
        "reasoning_delta",
        "activity",
        "activity",
        "done",
    ]
    assert all(event.message is None for event in events[:-1])
    message = events[-1].message
    assert message is not None
    assert message.stop_reason == "tool_calls"
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0].name == "edit_execute"
    assert message.tool_calls[0].arguments == {"edits": []}


def test_openai_chat_stream_closes_provider_and_client_when_closed_early(
    monkeypatch,
) -> None:
    provider_stream = AsyncStream(
        [
            SimpleNamespace(
                id="chunk-early-close",
                choices=[
                    SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(content="first"),
                    ),
                ],
            ),
        ],
    )

    class FakeClient:
        def __init__(self) -> None:
            self.close_count = 0
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **_: Any) -> AsyncStream:
            return provider_stream

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    async def consume_one_event() -> None:
        stream = async_stream_chat(
            _config(),
            [{"role": "user", "content": "hello"}],
        )
        event = await anext(stream)
        assert (event.type, event.delta) == ("text_delta", "first")

        await stream.aclose()

        assert provider_stream.close_count == 1
        assert client.close_count == 1

    asyncio.run(consume_one_event())


def test_openai_responses_stream_closes_provider_and_client_when_cancelled(
    monkeypatch,
) -> None:
    class BlockingStream:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.close_count = 0

        def __aiter__(self) -> "BlockingStream":
            return self

        async def __anext__(self) -> object:
            self.started.set()
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def close(self) -> None:
            self.close_count += 1

    class FakeClient:
        def __init__(self, provider_stream: BlockingStream) -> None:
            self.provider_stream = provider_stream
            self.close_count = 0
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> BlockingStream:
            return self.provider_stream

        async def close(self) -> None:
            self.close_count += 1

    async def consume_until_cancelled() -> None:
        provider_stream = BlockingStream()
        client = FakeClient(provider_stream)
        monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)
        consumer = asyncio.create_task(
            _collect_stream(
                async_stream_chat(
                    _config(api_family="openai_responses"),
                    [{"role": "user", "content": "hello"}],
                ),
            ),
        )
        await asyncio.wait_for(provider_stream.started.wait(), timeout=1)

        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(consumer, timeout=1)

        assert provider_stream.close_count == 1
        assert client.close_count == 1

    asyncio.run(consume_until_cancelled())


def test_openai_responses_adapter_flattens_tools(monkeypatch) -> None:
    class FakeResponses:
        create_params: dict[str, Any] = {}

        async def create(self, **kwargs: Any) -> object:
            FakeResponses.create_params = kwargs
            return SimpleNamespace(
                id="resp-1",
                output_text="",
                usage=SimpleNamespace(
                    input_tokens=7,
                    output_tokens=3,
                    total_tokens=10,
                ),
                output=[
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "edit_execute",
                        "arguments": '{"edits":[]}',
                    },
                ],
            )

    class FakeAsyncOpenAI:
        def __init__(self, **_: Any) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(common, "AsyncOpenAI", FakeAsyncOpenAI)
    config = _config(
        base_url="https://api.openai.com/v1",
        temperature=None,
        top_p=None,
        api_family="openai_responses",
        supports_thinking=True,
        thinking_enabled=True,
    )

    message = asyncio.run(
        async_complete_tool_call(
            config,
            [
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "hello"},
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "edit_execute",
                        "description": "Execute edits",
                        "parameters": {
                            "type": "object",
                            "properties": {"edits": {"type": "array"}},
                            "required": ["edits"],
                            "additionalProperties": False,
                        },
                    },
                },
            ],
        ),
    )

    assert message.tool_calls[0].id == "call-1"
    assert message.tool_calls[0].arguments == {"edits": []}
    assert message.usage and message.usage.input_tokens == 7
    assert FakeResponses.create_params["instructions"] == "system text"
    assert FakeResponses.create_params["input"] == [
        {"role": "user", "content": "hello"},
    ]
    assert FakeResponses.create_params["tools"] == [
        {
            "type": "function",
            "name": "edit_execute",
            "description": "Execute edits",
            "parameters": {
                "type": "object",
                "properties": {"edits": {"type": "array"}},
                "required": ["edits"],
                "additionalProperties": False,
            },
            "strict": False,
        },
    ]
    assert FakeResponses.create_params["reasoning"] == {"effort": "medium"}


def test_openai_responses_stream_maps_provider_events(monkeypatch) -> None:
    class FakeResponses:
        create_params: dict[str, Any] = {}

        async def create(self, **kwargs: Any) -> object:
            FakeResponses.create_params = kwargs
            return AsyncStream(
                [
                    SimpleNamespace(
                        type="response.reasoning_text.delta",
                        delta="think ",
                    ),
                    SimpleNamespace(type="response.output_text.delta", delta="Hi"),
                    SimpleNamespace(
                        type="response.completed",
                        response=SimpleNamespace(
                            id="resp-stream",
                            output_text="Hi",
                            usage=SimpleNamespace(
                                input_tokens=2,
                                output_tokens=1,
                                total_tokens=3,
                            ),
                            status="completed",
                        ),
                    ),
                ],
            )

    class FakeAsyncOpenAI:
        def __init__(self, **_: Any) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(common, "AsyncOpenAI", FakeAsyncOpenAI)

    events = asyncio.run(
        _collect_stream(
            async_stream_chat(
                _config(api_family="openai_responses"),
                [{"role": "user", "content": "hello"}],
            ),
        ),
    )

    assert FakeResponses.create_params["stream"] is True
    assert [(event.type, event.delta) for event in events[:-1]] == [
        ("reasoning_delta", "think "),
        ("text_delta", "Hi"),
    ]
    assert events[-1].type == "done"
    assert events[-1].message
    assert events[-1].message.content == "Hi"
    assert events[-1].message.reasoning == "think"
    assert events[-1].message.usage and events[-1].message.usage.total_tokens == 3


def test_sse_json_payload_parses_event_name_and_done_marker() -> None:
    assert common._sse_json_payload("message_delta", ['{"delta":"Hi"}']) == {
        "delta": "Hi",
        "_event": "message_delta",
    }
    assert common._sse_json_payload("", ["[DONE]"]) is None


def test_tool_argument_validation_returns_repair_error(monkeypatch) -> None:
    class FakeChatCompletions:
        async def create(self, **_: Any) -> object:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call-1",
                                    function=SimpleNamespace(
                                        name="resume_lookup",
                                        arguments='{"unknown":true}',
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            )

    class FakeAsyncOpenAI:
        def __init__(self, **_: Any) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=FakeChatCompletions().create),
            )

    monkeypatch.setattr(common, "AsyncOpenAI", FakeAsyncOpenAI)

    message = asyncio.run(
        async_complete_tool_call(
            _config(),
            [{"role": "user", "content": "find project"}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "resume_lookup",
                        "description": "Lookup resume",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                },
            ],
        ),
    )

    assert message.tool_calls == []
    assert message.validation_errors
    assert message.validation_errors[0].tool_call.id == "call-1"
    assert "required property" in message.validation_errors[0].message


def test_tool_argument_validation_retries_the_complete_unexecuted_batch(
    monkeypatch,
) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "gemini-mixed",
            "status": "requires_action",
            "steps": [
                {"type": "thought", "text": "Need two lookups."},
                {
                    "type": "function_call",
                    "id": "fc-valid",
                    "name": "resume_lookup",
                    "arguments": {"query": "skills"},
                },
                {
                    "type": "function_call",
                    "id": "fc-invalid",
                    "name": "resume_lookup",
                    "arguments": {"unknown": True},
                },
            ],
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)

    message = asyncio.run(
        async_complete_tool_call(
            _config(api_family="google_gemini"),
            [{"role": "user", "content": "find skills"}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "resume_lookup",
                        "description": "Lookup resume",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                },
            ],
        ),
    )

    assert message.tool_calls == []
    assert [error.tool_call.id for error in message.validation_errors] == [
        "fc-valid",
        "fc-invalid",
    ]
    assert "not executed" in message.validation_errors[0].message
    assert "required property" in message.validation_errors[1].message
    assert message.provider_state == {
        "steps": [
            {"type": "thought", "text": "Need two lookups."},
            {
                "type": "function_call",
                "id": "fc-valid",
                "name": "resume_lookup",
                "arguments": {"query": "skills"},
            },
            {
                "type": "function_call",
                "id": "fc-invalid",
                "name": "resume_lookup",
                "arguments": {"unknown": True},
            },
        ],
    }


def test_anthropic_adapter_maps_tool_schema_and_calls(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(url: str, **kwargs: Any) -> dict[str, Any]:
        captured["url"] = url
        captured.update(kwargs)
        return {
            "id": "msg-1",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 8, "output_tokens": 2},
            "content": [
                {"type": "text", "text": "checking"},
                {
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "resume_lookup",
                    "input": {"query": "project"},
                },
            ],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)
    config = _config(
        provider="anthropic",
        model="claude-test",
        base_url="https://api.anthropic.com/v1",
        api_family="anthropic_messages",
        temperature=None,
        top_p=None,
    )

    message = asyncio.run(
        async_complete_tool_call(
            config,
            [
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "hello"},
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "resume_lookup",
                        "description": "Lookup resume",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                },
            ],
        ),
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-test-secret"
    assert captured["payload"]["system"] == "system text"
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": "hello"},
    ]
    assert captured["payload"]["tools"][0]["input_schema"] == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }
    assert message.content == "checking"
    assert message.stop_reason == "tool_calls"
    assert message.usage and message.usage.total_tokens == 10
    assert message.tool_calls[0].id == "toolu-1"
    assert message.tool_calls[0].arguments == {"query": "project"}


def test_anthropic_thinking_tool_roundtrip_replays_signed_block(
    monkeypatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured_payloads.append(kwargs["payload"])
        if len(captured_payloads) == 1:
            return {
                "id": "msg-thinking-tool",
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "I should inspect the resume.",
                        "signature": "signed-thinking-block",
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu-thinking",
                        "name": "resume_lookup",
                        "input": {"query": "project"},
                    },
                ],
            }
        return {
            "id": "msg-after-tool",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)
    config = _config(
        provider="anthropic",
        model="claude-thinking",
        base_url="https://api.anthropic.com/v1",
        api_family="anthropic_messages",
        supports_thinking=True,
        thinking_enabled=True,
        temperature=None,
        top_p=None,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "resume_lookup",
                "description": "Lookup resume",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
    ]

    first = asyncio.run(
        async_complete_tool_call(
            config,
            [{"role": "user", "content": "Inspect my project."}],
            tools,
        ),
    )
    assert first.reasoning == "I should inspect the resume."
    assert first.provider_state == {
        "thinking_blocks": [
            {
                "type": "thinking",
                "thinking": "I should inspect the resume.",
                "signature": "signed-thinking-block",
            },
        ],
    }

    second = asyncio.run(
        async_complete_tool_call(
            config,
            [
                {"role": "user", "content": "Inspect my project."},
                {
                    "role": "assistant",
                    "content": first.content or None,
                    "tool_calls": [
                        {
                            "id": first.tool_calls[0].id,
                            "type": "function",
                            "function": {
                                "name": first.tool_calls[0].name,
                                "arguments": first.tool_calls[0].raw_arguments,
                            },
                        },
                    ],
                    "reasoning_content": first.reasoning,
                    "provider_state": first.provider_state,
                },
                {
                    "role": "tool",
                    "tool_call_id": first.tool_calls[0].id,
                    "content": '{"matches":["Project A"]}',
                },
            ],
            tools,
        ),
    )

    assert second.content == "Done"
    assert captured_payloads[1]["messages"] == [
        {"role": "user", "content": "Inspect my project."},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "I should inspect the resume.",
                    "signature": "signed-thinking-block",
                },
                {
                    "type": "tool_use",
                    "id": "toolu-thinking",
                    "name": "resume_lookup",
                    "input": {"query": "project"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu-thinking",
                    "content": '{"matches":["Project A"]}',
                },
            ],
        },
    ]


def test_anthropic_stream_maps_sse_events(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_stream_json(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        for event in [
            {
                "type": "message_start",
                "message": {
                    "id": "msg-stream",
                    "usage": {"input_tokens": 4},
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
                "delta": {"type": "thinking_delta", "thinking": "think "},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "signature_delta",
                    "signature": "stream-signature",
                },
            },
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Hello"},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 2},
            },
            {"type": "message_stop"},
        ]:
            yield event

    monkeypatch.setattr(anthropic_messages, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect_stream(
            async_stream_chat(
                _config(
                    provider="anthropic",
                    base_url="https://api.anthropic.com/v1",
                    api_family="anthropic_messages",
                ),
                [{"role": "user", "content": "hello"}],
            ),
        ),
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["payload"]["stream"] is True
    assert [(event.type, event.delta) for event in events[:-1]] == [
        ("activity", ""),
        ("reasoning_delta", "think "),
        ("activity", ""),
        ("text_delta", "Hello"),
        ("activity", ""),
    ]
    assert events[-1].type == "done"
    assert events[-1].message
    assert events[-1].message.content == "Hello"
    assert events[-1].message.reasoning == "think"
    assert events[-1].message.response_id == "msg-stream"
    assert events[-1].message.provider_state == {
        "thinking_blocks": [
            {
                "type": "thinking",
                "thinking": "think ",
                "signature": "stream-signature",
            },
        ],
    }
    assert events[-1].message.usage and events[-1].message.usage.total_tokens == 6

    _, replayed = anthropic_messages.anthropic_messages(
        [
            {
                "role": "assistant",
                "provider_state": events[-1].message.provider_state,
                "tool_calls": [
                    {
                        "id": "toolu-stream",
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "arguments": '{"query":"project"}',
                        },
                    },
                ],
            },
        ],
    )
    assert replayed == [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "think ",
                    "signature": "stream-signature",
                },
                {
                    "type": "tool_use",
                    "id": "toolu-stream",
                    "name": "resume_lookup",
                    "input": {"query": "project"},
                },
            ],
        },
    ]


def test_gemini_adapter_builds_stateless_interaction(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(url: str, **kwargs: Any) -> dict[str, Any]:
        captured["url"] = url
        captured.update(kwargs)
        return {
            "id": "gemini-1",
            "status": "requires_action",
            "usageMetadata": {
                "promptTokenCount": 6,
                "candidatesTokenCount": 3,
                "totalTokenCount": 9,
            },
            "steps": [
                {
                    "type": "function_call",
                    "id": "fc-1",
                    "name": "resume_lookup",
                    "arguments": {"query": "skills"},
                },
            ],
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)
    config = _config(
        provider="google",
        model="gemini-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_family="google_gemini",
        temperature=None,
        top_p=None,
    )

    message = asyncio.run(
        async_complete_tool_call(
            config,
            [
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "hello"},
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "resume_lookup",
                        "description": "Lookup resume",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                },
            ],
        ),
    )

    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/interactions"
    )
    assert captured["headers"]["x-goog-api-key"] == "sk-test-secret"
    assert captured["payload"]["store"] is False
    assert captured["payload"]["system_instruction"] == "system text"
    assert captured["payload"]["input"] == [
        {
            "type": "user_input",
            "content": [
                {
                    "type": "text",
                    "text": "hello",
                },
            ],
        },
    ]
    assert captured["payload"]["tools"][0]["name"] == "resume_lookup"
    assert message.tool_calls[0].id == "fc-1"
    assert message.usage and message.usage.total_tokens == 9
    assert message.provider_state == {
        "steps": [
            {
                "type": "function_call",
                "id": "fc-1",
                "name": "resume_lookup",
                "arguments": {"query": "skills"},
            },
        ],
    }


def test_gemini_payload_replays_provider_state_before_tool_result() -> None:
    payload = google_gemini.gemini_payload(
        _config(api_family="google_gemini"),
        [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": None,
                "provider_state": {
                    "steps": [
                        {
                            "type": "thought",
                            "text": "Need resume context.",
                        },
                        {
                            "type": "function_call",
                            "id": "fc-1",
                            "name": "resume_lookup",
                            "arguments": {"query": "skills"},
                        },
                    ],
                },
            },
            {
                "role": "tool",
                "tool_call_id": "fc-1",
                "content": '{"matches":["Python"]}',
            },
        ],
    )

    assert payload["input"] == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "hello"}],
        },
        {
            "type": "thought",
            "text": "Need resume context.",
        },
        {
            "type": "function_call",
            "id": "fc-1",
            "name": "resume_lookup",
            "arguments": {"query": "skills"},
        },
        {
            "type": "function_result",
            "name": "resume_lookup",
            "call_id": "fc-1",
            "result": [{"type": "text", "text": '{"matches":["Python"]}'}],
        },
    ]


@pytest.mark.parametrize("status", ["incomplete", "budget_exceeded"])
def test_gemini_unary_tool_call_drops_tools_from_incomplete_status(
    monkeypatch,
    status: str,
) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "gemini-unary-incomplete",
            "status": status,
            "steps": [
                {
                    "type": "function_call",
                    "id": "fc-incomplete",
                    "name": "resume_lookup",
                    "arguments": {"query": "skills"},
                },
            ],
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)

    message = asyncio.run(
        google_gemini.complete_tool_call(
            _config(api_family="google_gemini"),
            [{"role": "user", "content": "find skills"}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "resume_lookup",
                        "parameters": {"type": "object"},
                    },
                },
            ],
        ),
    )

    assert message.stop_reason == "length"
    assert message.tool_calls == []
    assert message.provider_state == {}


@pytest.mark.parametrize("status", ["failed", "cancelled", "unknown", None])
def test_gemini_unary_rejects_unsuccessful_terminal_status(
    monkeypatch,
    status: str | None,
) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "gemini-unary-failed",
            "status": status,
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "unsafe partial"}],
                },
            ],
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)

    with pytest.raises(LlmRequestError, match="did not complete successfully"):
        asyncio.run(
            google_gemini.complete(
                _config(api_family="google_gemini"),
                [{"role": "user", "content": "hello"}],
            ),
        )


def test_gemini_unary_rejects_function_call_from_completed_status(
    monkeypatch,
) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "gemini-unary-completed-call",
            "status": "completed",
            "steps": [
                {
                    "type": "function_call",
                    "id": "fc-completed",
                    "name": "resume_lookup",
                    "arguments": {"query": "skills"},
                },
            ],
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)

    with pytest.raises(LlmRequestError, match="completed.*function call"):
        asyncio.run(
            google_gemini.complete_tool_call(
                _config(api_family="google_gemini"),
                [{"role": "user", "content": "find skills"}],
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "parameters": {"type": "object"},
                        },
                    },
                ],
            ),
        )


@pytest.mark.parametrize(
    "second_call",
    [
        {
            "type": "function_call",
            "id": "fc-malformed",
            "arguments": {"query": "projects"},
        },
        {
            "type": "function_call",
            "id": "fc-valid",
            "name": "resume_lookup",
            "arguments": {"query": "projects"},
        },
    ],
    ids=["missing-name", "duplicate-id"],
)
def test_gemini_unary_rejects_invalid_function_call_batch(
    monkeypatch,
    second_call: dict[str, Any],
) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "gemini-invalid-batch",
            "status": "requires_action",
            "steps": [
                {
                    "type": "function_call",
                    "id": "fc-valid",
                    "name": "resume_lookup",
                    "arguments": {"query": "skills"},
                },
                second_call,
            ],
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)

    with pytest.raises(LlmRequestError, match="invalid function call batch"):
        asyncio.run(
            google_gemini.complete_tool_call(
                _config(api_family="google_gemini"),
                [{"role": "user", "content": "find skills"}],
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "parameters": {"type": "object"},
                        },
                    },
                ],
            ),
        )


def test_gemini_stream_maps_sse_events(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_stream_json(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        for event in [
            {
                "event_type": "interaction.created",
                "interaction": {
                    "id": "gemini-stream",
                    "status": "in_progress",
                },
            },
            {"event_type": "ping"},
            {"event_type": "heartbeat"},
            {
                "event_type": "interaction.status_update",
                "interaction_id": "gemini-stream",
                "status": "in_progress",
            },
            {
                "event_type": "interaction.status_update",
                "interaction_id": "gemini-stream",
                "status": "queued",
            },
            {
                "event_type": "interaction.status_update",
                "interaction_id": "gemini-stream",
                "status": "unknown",
            },
            {
                "event_type": "step.start",
                "index": 0,
                "step": {"type": "model_output"},
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {"type": "text", "text": ""},
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {"type": "unknown"},
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {"type": "text", "text": "Hel"},
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {"type": "text", "text": "lo"},
            },
            {"event_type": "step.stop", "index": 0},
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "gemini-stream",
                    "status": "completed",
                    "usage": {
                        "total_input_tokens": 3,
                        "total_output_tokens": 2,
                        "total_tokens": 5,
                    },
                },
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect_stream(
            async_stream_chat(
                _config(
                    provider="google",
                    base_url="https://generativelanguage.googleapis.com/v1beta",
                    api_family="google_gemini",
                ),
                [{"role": "user", "content": "hello"}],
            ),
        ),
    )

    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/interactions?alt=sse"
    )
    assert captured["payload"]["stream"] is True
    assert [(event.type, event.delta) for event in events] == [
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
        ("text_delta", "Hel"),
        ("text_delta", "lo"),
        ("activity", ""),
        ("done", ""),
    ]
    assert events[-1].type == "done"
    assert events[-1].message
    assert events[-1].message.content == "Hello"
    assert events[-1].message.usage and events[-1].message.usage.total_tokens == 5


def test_gemini_tool_stream_buffers_arguments_until_authoritative_completion(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_stream_json(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        for event in [
            {
                "event_type": "interaction.created",
                "interaction": {
                    "id": "gemini-tool-stream",
                    "status": "in_progress",
                },
            },
            {
                "event_type": "step.start",
                "index": 2,
                "step": {"type": "thought"},
            },
            {
                "event_type": "step.delta",
                "index": 2,
                "delta": {
                    "type": "thought_summary",
                    "content": {"type": "text", "text": ""},
                },
            },
            {
                "event_type": "step.delta",
                "index": 2,
                "delta": {"type": "thought_signature", "signature": ""},
            },
            {
                "event_type": "step.delta",
                "index": 2,
                "delta": {
                    "type": "thought_summary",
                    "content": {"type": "text", "text": "Need resume context."},
                },
            },
            {
                "event_type": "step.delta",
                "index": 2,
                "delta": {"type": "thought_signature", "signature": "sig-1"},
            },
            {"event_type": "step.stop", "index": 2},
            {
                "event_type": "step.start",
                "index": 5,
                "step": {
                    "type": "function_call",
                    "id": "fc-stream",
                    "name": "resume_lookup",
                    "arguments": {},
                },
            },
            {
                "event_type": "step.delta",
                "index": 5,
                "delta": {"type": "arguments_delta", "arguments": ""},
            },
            {
                "event_type": "step.delta",
                "index": 5,
                "delta": {
                    "type": "arguments_delta",
                    "arguments": '{"query":',
                },
            },
            {
                "event_type": "step.delta",
                "index": 5,
                "delta": {"type": "arguments_delta", "arguments": '"skills"}'},
            },
            {"event_type": "step.stop", "index": 5},
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "gemini-tool-stream",
                    "status": "requires_action",
                    "usage": {
                        "total_input_tokens": 7,
                        "total_output_tokens": 4,
                        "total_tokens": 11,
                        "total_cached_tokens": 2,
                        "total_thought_tokens": 3,
                    },
                },
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect_stream(
            google_gemini.stream_tool_call(
                _config(
                    provider="google",
                    base_url=("https://generativelanguage.googleapis.com/v1beta"),
                    api_family="google_gemini",
                ),
                [{"role": "user", "content": "find skills"}],
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "description": "Lookup resume",
                            "parameters": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                                "required": ["query"],
                            },
                        },
                    },
                ],
            ),
        ),
    )

    assert captured["payload"]["stream"] is True
    assert captured["payload"]["tools"][0]["name"] == "resume_lookup"
    assert [(event.type, event.delta) for event in events] == [
        ("activity", ""),
        ("activity", ""),
        ("reasoning_delta", "Need resume context."),
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
        ("activity", ""),
        ("done", ""),
    ]
    assert all(event.message is None for event in events[:-1])
    message = events[-1].message
    assert message
    assert message.response_id == "gemini-tool-stream"
    assert message.reasoning == "Need resume context."
    assert message.stop_reason == "tool_calls"
    assert message.tool_calls[0].id == "fc-stream"
    assert message.tool_calls[0].name == "resume_lookup"
    assert message.tool_calls[0].arguments == {"query": "skills"}
    assert message.tool_calls[0].raw_arguments == '{"query":"skills"}'
    assert message.usage
    assert message.usage.input_tokens == 7
    assert message.usage.output_tokens == 4
    assert message.usage.total_tokens == 11
    assert message.usage.cached_input_tokens == 2
    assert message.usage.reasoning_tokens == 3
    assert message.provider_state == {
        "steps": [
            {
                "type": "thought",
                "summary": [{"type": "text", "text": "Need resume context."}],
                "signature": "sig-1",
            },
            {
                "type": "function_call",
                "id": "fc-stream",
                "name": "resume_lookup",
                "arguments": {"query": "skills"},
            },
        ],
    }


def test_gemini_tool_stream_never_exposes_calls_from_incomplete_terminal(
    monkeypatch,
) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {
                    "type": "function_call",
                    "id": "fc-truncated",
                    "name": "resume_lookup",
                    "arguments": {},
                },
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {
                    "type": "arguments_delta",
                    "arguments": '{"query":"skills"}',
                },
            },
            {"event_type": "step.stop", "index": 0},
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "gemini-incomplete",
                    "status": "incomplete",
                },
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    events = asyncio.run(
        _collect_stream(
            google_gemini.stream_tool_call(
                _config(api_family="google_gemini"),
                [{"role": "user", "content": "find skills"}],
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "parameters": {"type": "object"},
                        },
                    },
                ],
            ),
        ),
    )

    message = events[-1].message
    assert message
    assert message.stop_reason == "length"
    assert message.tool_calls == []
    assert message.provider_state == {}


def test_gemini_tool_stream_rejects_malformed_call_in_mixed_batch(
    monkeypatch,
) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {
                    "type": "function_call",
                    "id": "fc-valid",
                    "name": "resume_lookup",
                    "arguments": {},
                },
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {
                    "type": "arguments_delta",
                    "arguments": '{"query":"skills"}',
                },
            },
            {"event_type": "step.stop", "index": 0},
            {
                "event_type": "step.start",
                "index": 1,
                "step": {
                    "type": "function_call",
                    "id": "fc-malformed",
                    "arguments": {},
                },
            },
            {"event_type": "step.stop", "index": 1},
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "gemini-invalid-stream-batch",
                    "status": "requires_action",
                },
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="invalid function call batch"):
        asyncio.run(
            _collect_stream(
                google_gemini.stream_tool_call(
                    _config(api_family="google_gemini"),
                    [{"role": "user", "content": "find skills"}],
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "resume_lookup",
                                "parameters": {"type": "object"},
                            },
                        },
                    ],
                ),
            ),
        )


def test_gemini_tool_stream_rejects_eof_before_completed_event(monkeypatch) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {
                    "type": "function_call",
                    "id": "fc-no-terminal",
                    "name": "resume_lookup",
                    "arguments": {},
                },
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {
                    "type": "arguments_delta",
                    "arguments": '{"query":"skills"}',
                },
            },
            {"event_type": "step.stop", "index": 0},
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)
    seen: list[Any] = []

    async def consume() -> None:
        async for event in google_gemini.stream_tool_call(
            _config(api_family="google_gemini"),
            [{"role": "user", "content": "find skills"}],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "resume_lookup",
                        "parameters": {"type": "object"},
                    },
                },
            ],
        ):
            seen.append(event)

    with pytest.raises(LlmRequestError, match="before completion"):
        asyncio.run(consume())

    assert seen
    assert all(event.message is None for event in seen)


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_gemini_stream_rejects_unsuccessful_completed_status(
    monkeypatch,
    status: str,
) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        yield {
            "event_type": "interaction.completed",
            "interaction": {"id": "gemini-failed", "status": status},
        }

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="did not complete successfully"):
        asyncio.run(
            _collect_stream(
                google_gemini.stream(
                    _config(api_family="google_gemini"),
                    [{"role": "user", "content": "hello"}],
                ),
            ),
        )


def test_gemini_tool_stream_rejects_requires_action_without_valid_call(
    monkeypatch,
) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {"type": "function_call", "arguments": {}},
            },
            {"event_type": "step.stop", "index": 0},
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "gemini-invalid-action",
                    "status": "requires_action",
                },
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="valid function call"):
        asyncio.run(
            _collect_stream(
                google_gemini.stream_tool_call(
                    _config(api_family="google_gemini"),
                    [{"role": "user", "content": "find skills"}],
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "resume_lookup",
                                "parameters": {"type": "object"},
                            },
                        },
                    ],
                ),
            ),
        )


@pytest.mark.parametrize(
    "events",
    [
        [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {"type": "function_call", "id": "fc-a", "name": "a"},
            },
            {
                "event_type": "step.start",
                "index": 0,
                "step": {"type": "function_call", "id": "fc-b", "name": "b"},
            },
        ],
        [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {"type": "model_output"},
            },
            {"event_type": "step.stop", "index": 0},
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {"type": "text", "text": "late"},
            },
        ],
        [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {"type": "model_output"},
            },
            {"event_type": "step.stop", "index": 0},
            {"event_type": "step.stop", "index": 0},
        ],
    ],
    ids=["duplicate-start", "delta-after-stop", "duplicate-stop"],
)
def test_gemini_stream_rejects_invalid_step_lifecycle(
    monkeypatch,
    events: list[dict[str, Any]],
) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in events:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="invalid stream step lifecycle"):
        asyncio.run(
            _collect_stream(
                google_gemini.stream(
                    _config(api_family="google_gemini"),
                    [{"role": "user", "content": "hello"}],
                ),
            ),
        )


def test_gemini_stream_closes_provider_stream_when_cancelled(monkeypatch) -> None:
    class BlockingStream:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.close_count = 0

        def __aiter__(self) -> "BlockingStream":
            return self

        async def __anext__(self) -> dict[str, Any]:
            self.started.set()
            await asyncio.Event().wait()
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.close_count += 1

    async def cancel_stream() -> None:
        provider_stream = BlockingStream()
        monkeypatch.setattr(
            google_gemini,
            "async_stream_json",
            lambda *_args, **_kwargs: provider_stream,
        )
        consumer = asyncio.create_task(
            _collect_stream(
                google_gemini.stream(
                    _config(api_family="google_gemini"),
                    [{"role": "user", "content": "hello"}],
                ),
            ),
        )
        await asyncio.wait_for(provider_stream.started.wait(), timeout=1)

        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(consumer, timeout=1)

        assert provider_stream.close_count == 1

    asyncio.run(cancel_stream())


async def _collect_stream(stream: Any) -> list[Any]:
    return [event async for event in stream]
