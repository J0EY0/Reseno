import asyncio
from types import SimpleNamespace
from typing import Any

from app.services.llm import (
    AgentLlmConfig,
    async_complete_chat,
    async_complete_tool_call,
    async_stream_chat,
    common,
)
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
)


class AsyncStream:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "AsyncStream":
        return self

    async def __anext__(self) -> object:
        if not self._chunks:
            raise StopAsyncIteration

        return self._chunks.pop(0)

    async def close(self) -> None:
        return None


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
    assert FakeAsyncOpenAI.init_kwargs["timeout"] == 12
    assert FakeChatCompletions.create_params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.3,
        "top_p": 0.8,
        "stream": False,
        "max_tokens": 256,
    }


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
        ("reasoning_delta", "think "),
        ("text_delta", "Hello"),
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


def test_gemini_stream_maps_sse_events(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_stream_json(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured.update(kwargs)
        for event in [
            {"output_text": "Hel"},
            {
                "id": "gemini-stream",
                "output_text": "Hello",
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
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
    assert [(event.type, event.delta) for event in events[:-1]] == [
        ("text_delta", "Hel"),
        ("text_delta", "lo"),
    ]
    assert events[-1].type == "done"
    assert events[-1].message
    assert events[-1].message.content == "Hello"
    assert events[-1].message.usage and events[-1].message.usage.total_tokens == 5


async def _collect_stream(stream: Any) -> list[Any]:
    return [event async for event in stream]
