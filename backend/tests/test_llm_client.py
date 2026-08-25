import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIStatusError
from openai.types.chat import ChatCompletionChunk

from app.services.llm import (
    AgentLlmConfig,
    LlmPrompt,
    LlmRequestContext,
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
        async_complete_chat(
            config, LlmPrompt(messages=[{"role": "user", "content": "hello"}])
        ),
    )

    assert message.content == "SDK response"
    assert message.stop_reason == "stop"
    assert message.usage and message.usage.total_tokens == 14
    assert FakeAsyncOpenAI.init_kwargs["api_key"] == "sk-test-secret"
    assert FakeAsyncOpenAI.init_kwargs["base_url"] == "https://api.example.test/v1"
    assert FakeAsyncOpenAI.init_kwargs["max_retries"] == 0
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


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [("moonshot", "https://api.moonshot.ai/v1")],
)
def test_official_chat_provider_sends_request_prompt_cache_key(
    monkeypatch,
    provider: str,
    base_url: str,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="chatcmpl-cache",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="cached"),
                    ),
                ],
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    message = asyncio.run(
        async_complete_chat(
            _config(
                provider=provider,
                provider_kind="cloud",
                api_family="openai_compatible_chat",
                base_url=base_url,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        ),
    )

    assert message.content == "cached"
    assert client.params["prompt_cache_key"] == "resume-session-1"


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("openai", "https://api.openai.com/v1"),
        ("xai", "https://api.x.ai/v1"),
    ],
)
def test_official_responses_provider_sends_request_prompt_cache_key(
    monkeypatch,
    provider: str,
    base_url: str,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-cache",
                output_text="cached",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    message = asyncio.run(
        async_complete_chat(
            _config(
                provider=provider,
                provider_kind="cloud",
                api_family="openai_responses",
                base_url=base_url,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        ),
    )

    assert message.content == "cached"
    assert client.params["prompt_cache_key"] == "resume-session-1"


def test_openai_gpt_5_6_responses_marks_only_the_declared_stable_prefix(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-explicit-cache",
                output_text="cached",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    message = asyncio.run(
        async_complete_chat(
            _config(
                provider="openai",
                provider_kind="cloud",
                api_family="openai_responses",
                model="gpt-5.6-terra",
                base_url="https://api.openai.com/v1",
            ),
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "stable instructions"},
                    {"role": "user", "content": "stable historical turn"},
                    {"role": "assistant", "content": "stable historical answer"},
                    {"role": "user", "content": "current workspace"},
                    {"role": "user", "content": "current changing request"},
                ],
                stable_prefix_message_counts=(2, 3, 5),
            ),
            request_context=LlmRequestContext(
                cache_key="resume-session-1",
            ),
        ),
    )

    assert message.content == "cached"
    assert client.params["prompt_cache_key"] == "resume-session-1"
    assert client.params["extra_body"] == {
        "prompt_cache_options": {"mode": "explicit"},
    }
    input_items = client.params["input"]
    assert input_items[-4]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
    }
    assert input_items[-3]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
    }
    assert "prompt_cache_breakpoint" not in input_items[-2]["content"][0]
    assert input_items[-1]["content"][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
    }


def test_openai_gpt_5_6_without_a_stable_prefix_keeps_implicit_cache(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-implicit-cache",
                output_text="cached",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    asyncio.run(
        openai_responses.complete(
            _config(
                provider="openai",
                provider_kind="cloud",
                api_family="openai_responses",
                model="gpt-5.6",
                base_url="https://api.openai.com/v1",
            ),
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "stable instructions"},
                    {"role": "user", "content": "current workspace"},
                    {"role": "user", "content": "current changing request"},
                ]
            ),
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        ),
    )

    assert client.params["prompt_cache_key"] == "resume-session-1"
    assert "extra_body" not in client.params
    assert all(
        "prompt_cache_breakpoint" not in part
        for item in client.params["input"]
        for part in item.get("content", [])
        if isinstance(part, dict)
    )


@pytest.mark.parametrize(
    ("provider", "provider_kind", "model"),
    [
        ("openai", "cloud", "gpt-5.5"),
        ("openai", "cloud", "gpt-test"),
        ("xai", "cloud", "grok-4.5"),
        ("openai", "custom", "gpt-5.6-terra"),
    ],
)
def test_unsupported_responses_provider_does_not_receive_explicit_cache_fields(
    monkeypatch,
    provider: str,
    provider_kind: str,
    model: str,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-implicit-cache",
                output_text="cached",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    asyncio.run(
        openai_responses.complete(
            _config(
                provider=provider,
                provider_kind=provider_kind,
                api_family="openai_responses",
                model=model,
            ),
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "stable instructions"},
                    {"role": "user", "content": "current changing request"},
                ]
            ),
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        ),
    )

    assert "extra_body" not in client.params
    for item in client.params["input"]:
        content = item.get("content")
        if isinstance(content, list):
            assert all("prompt_cache_breakpoint" not in part for part in content)


def test_deepseek_chat_usage_normalizes_official_cache_hit_tokens() -> None:
    usage = common.openai_chat_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=8,
                total_tokens=128,
                prompt_cache_hit_tokens=96,
                prompt_cache_miss_tokens=24,
            ),
        ),
    )

    assert usage
    assert usage.input_tokens == 120
    assert usage.cached_input_tokens == 96
    assert usage.output_tokens == 8
    assert usage.total_tokens == 128


def test_openai_compatible_usage_normalizes_standard_cached_tokens() -> None:
    usage = common.openai_chat_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=8,
                total_tokens=128,
                prompt_tokens_details=SimpleNamespace(cached_tokens=96),
            ),
        ),
    )

    assert usage
    assert usage.cached_input_tokens == 96


def test_moonshot_chat_usage_normalizes_official_cached_tokens() -> None:
    usage = common.openai_chat_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=8,
                total_tokens=128,
                cached_tokens=96,
            ),
        ),
    )

    assert usage
    assert usage.input_tokens == 120
    assert usage.cached_input_tokens == 96
    assert usage.output_tokens == 8
    assert usage.total_tokens == 128


@pytest.mark.parametrize("cache_key", ["", "   ", "x" * 65])
def test_llm_request_context_rejects_invalid_cache_keys(cache_key: str) -> None:
    with pytest.raises(ValueError):
        LlmRequestContext(cache_key=cache_key)


def test_llm_request_context_rejects_non_string_cache_key() -> None:
    with pytest.raises(TypeError):
        LlmRequestContext(cache_key=123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("provider", "provider_kind", "api_family", "base_url"),
    [
        ("openai", "cloud", "openai_compatible_chat", "https://api.openai.com/v1"),
        ("custom-cloud", "custom", "openai_compatible_chat", "https://proxy.test/v1"),
        ("moonshot", "custom", "openai_compatible_chat", "https://api.moonshot.ai/v1"),
        ("moonshot", "cloud", "openai_responses", "https://api.moonshot.ai/v1"),
        ("xai", "custom", "openai_responses", "https://api.x.ai/v1"),
        ("openai", "custom", "openai_compatible_chat", "https://api.openai.com/v1"),
        ("openai", "custom", "openai_responses", "https://api.openai.com/v1"),
        ("openai", "cloud", "openai_responses", "https://proxy.test/v1"),
        ("xai", "cloud", "openai_responses", "https://proxy.test/v1"),
        ("moonshot", "cloud", "openai_compatible_chat", "https://proxy.test/v1"),
    ],
)
def test_non_official_openai_providers_do_not_receive_prompt_cache_key(
    monkeypatch,
    provider: str,
    provider_kind: str,
    api_family: str,
    base_url: str,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create_chat),
            )
            self.responses = SimpleNamespace(create=self.create_response)

        async def create_chat(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="chatcmpl-custom",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="custom"),
                    ),
                ],
            )

        async def create_response(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-xai",
                output_text="xai",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    adapter = openai_responses if api_family == "openai_responses" else openai_chat
    monkeypatch.setattr(adapter, "async_openai_client", lambda _: client)

    asyncio.run(
        async_complete_chat(
            _config(
                provider=provider,
                provider_kind=provider_kind,
                api_family=api_family,
                base_url=base_url,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        ),
    )

    assert "prompt_cache_key" not in client.params


def test_moonshot_chat_tool_dispatch_sends_request_prompt_cache_key(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="chatcmpl-tool-cache",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="done", tool_calls=[]),
                    ),
                ],
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    asyncio.run(
        async_complete_tool_call(
            _config(
                provider="moonshot",
                provider_kind="cloud",
                api_family="openai_compatible_chat",
                base_url="https://api.moonshot.ai/v1",
                supports_streaming=False,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "inspect"}]),
            [],
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        ),
    )

    assert client.params["prompt_cache_key"] == "resume-session-1"


def test_qwen_supported_model_projects_only_the_latest_four_cache_boundaries(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="chatcmpl-qwen-cache",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="cached"),
                    ),
                ],
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)
    transcript: list[dict[str, Any]] = [
        {"role": "system", "content": "stable policy"},
    ]
    for index in range(5):
        transcript.append(
            {"role": "user", "content": f"replayable turn {index}"},
        )

    asyncio.run(
        openai_chat.complete(
            _config(
                provider="qwen",
                provider_kind="cloud",
                api_family="openai_compatible_chat",
                model="qwen3.7-plus",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            LlmPrompt(
                messages=transcript,  # type: ignore[arg-type]
                stable_prefix_message_counts=(2, 3, 4, 5, 6),
            ),
        ),
    )

    messages = client.params["messages"]
    assert messages[1]["content"] == "replayable turn 0"
    assert [
        message["content"][-1].get("cache_control") for message in messages[2:]
    ] == [{"type": "ephemeral"}] * 4


@pytest.mark.parametrize(
    ("provider_kind", "model"),
    [
        ("cloud", "qwen-max"),
        ("custom", "qwen3.7-plus"),
    ],
)
def test_qwen_unsupported_endpoint_or_model_keeps_implicit_cache_only(
    provider_kind: str,
    model: str,
) -> None:
    params = common.chat_completion_params(
        _config(
            provider="qwen",
            provider_kind=provider_kind,
            api_family="openai_compatible_chat",
            model=model,
        ),
        LlmPrompt(
            messages=[
                {"role": "user", "content": "stable history"},
                {"role": "user", "content": "current request"},
            ],
            stable_prefix_message_counts=(1,),
        ),
        stream=False,
    )

    assert params["messages"] == [
        {"role": "user", "content": "stable history"},
        {"role": "user", "content": "current request"},
    ]


@pytest.mark.parametrize(
    ("invalid_id", "invalid_name"),
    [
        (None, "resume_lookup"),
        ("", "resume_lookup"),
        ("call-invalid", None),
        ("call-invalid", ""),
    ],
)
def test_openai_chat_rejects_malformed_call_in_terminal_tool_batch(
    monkeypatch,
    invalid_id: str | None,
    invalid_name: str | None,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **_: Any) -> object:
            return SimpleNamespace(
                id="chatcmpl-invalid-tool-batch",
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call-valid",
                                    function=SimpleNamespace(
                                        name="resume_lookup",
                                        arguments="{}",
                                    ),
                                ),
                                SimpleNamespace(
                                    id=invalid_id,
                                    function=SimpleNamespace(
                                        name=invalid_name,
                                        arguments="{}",
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        openai_chat,
        "async_openai_client",
        lambda _: FakeClient(),
    )

    with pytest.raises(LlmRequestError, match="invalid function call batch"):
        asyncio.run(
            async_complete_tool_call(
                _config(supports_streaming=False),
                LlmPrompt(messages=[{"role": "user", "content": "Inspect my resume."}]),
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


def test_openai_responses_tool_dispatch_sends_request_prompt_cache_key(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-tool-cache",
                output_text="done",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    asyncio.run(
        async_complete_tool_call(
            _config(
                provider="openai",
                provider_kind="cloud",
                api_family="openai_responses",
                base_url="https://api.openai.com/v1",
                supports_streaming=False,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "inspect"}]),
            [],
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        ),
    )

    assert client.params["prompt_cache_key"] == "resume-session-1"


@pytest.mark.parametrize(
    ("invalid_id", "invalid_name"),
    [
        (None, "resume_lookup"),
        ("", "resume_lookup"),
        ("call-invalid", None),
        ("call-invalid", ""),
    ],
)
def test_openai_responses_rejects_malformed_call_in_terminal_tool_batch(
    monkeypatch,
    invalid_id: str | None,
    invalid_name: str | None,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> object:
            return SimpleNamespace(
                id="response-invalid-tool-batch",
                output_text="",
                output=[
                    {
                        "type": "function_call",
                        "call_id": "call-valid",
                        "name": "resume_lookup",
                        "arguments": "{}",
                    },
                    {
                        "type": "function_call",
                        "call_id": invalid_id,
                        "name": invalid_name,
                        "arguments": "{}",
                    },
                ],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        openai_responses,
        "async_openai_client",
        lambda _: FakeClient(),
    )

    with pytest.raises(LlmRequestError, match="invalid function call batch"):
        asyncio.run(
            async_complete_tool_call(
                _config(
                    api_family="openai_responses",
                    supports_streaming=False,
                ),
                LlmPrompt(messages=[{"role": "user", "content": "Inspect my resume."}]),
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
            LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
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
                LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
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
                LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
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
                LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
            ),
        )

    assert client.close_count == 1


def test_openai_chat_tool_error_is_not_retried(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.close_count = 0
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **params: Any) -> object:
            self.calls.append(params)
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

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)
    provider_attempts = 0

    def record_attempt() -> None:
        nonlocal provider_attempts
        provider_attempts += 1

    with pytest.raises(LlmRequestError):
        asyncio.run(
            async_complete_tool_call(
                _config(),
                LlmPrompt(messages=[{"role": "user", "content": "inspect"}]),
                [],
                on_provider_attempt=record_attempt,
            ),
        )

    assert len(client.calls) == 1
    assert client.close_count == 1
    assert provider_attempts == 1


def test_openai_chat_stream_tool_error_is_not_retried(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.close_count = 0
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **params: Any) -> object:
            self.calls.append(params)
            if len(self.calls) > 1:
                return AsyncStream([])
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

        async def close(self) -> None:
            self.close_count += 1

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    with pytest.raises(LlmRequestError):
        asyncio.run(
            _collect_stream(
                openai_chat.stream_tool_call(
                    _config(),
                    LlmPrompt(messages=[{"role": "user", "content": "inspect"}]),
                    [],
                ),
            ),
        )

    assert len(client.calls) == 1
    assert "parallel_tool_calls" not in client.calls[0]
    assert client.close_count == 1


def test_openai_chat_stream_returns_delta_and_done_message(monkeypatch) -> None:
    class FakeChatCompletions:
        async def create(self, **kwargs: Any) -> object:
            assert kwargs["stream"] is True
            assert kwargs["prompt_cache_key"] == "resume-session-1"
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
            async_stream_chat(
                _config(
                    provider="moonshot",
                    provider_kind="cloud",
                    base_url="https://api.moonshot.ai/v1",
                ),
                LlmPrompt(messages=[{"role": "user", "content": "hi"}]),
                request_context=LlmRequestContext(cache_key="resume-session-1"),
            ),
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
            assert kwargs["prompt_cache_key"] == "resume-session-1"
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
                _config(
                    provider="moonshot",
                    provider_kind="cloud",
                    base_url="https://api.moonshot.ai/v1",
                ),
                LlmPrompt(messages=[{"role": "user", "content": "edit"}]),
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
                request_context=LlmRequestContext(cache_key="resume-session-1"),
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
            LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
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
                    LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
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
    )

    message = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "system text"},
                    {"role": "user", "content": "hello"},
                ]
            ),
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
    assert "tool_choice" not in FakeResponses.create_params
    assert "reasoning" not in FakeResponses.create_params


def test_openai_responses_replays_encrypted_reasoning_before_tool_results(
    monkeypatch,
) -> None:
    reasoning_items = [
        {
            "type": "reasoning",
            "id": "reasoning-1",
            "encrypted_content": "opaque-encrypted-reasoning-1",
            "summary": [],
            "status": "completed",
        },
        {
            "type": "reasoning",
            "id": "reasoning-2",
            "encrypted_content": "opaque-encrypted-reasoning-2",
            "summary": [{"type": "summary_text", "text": "Inspect edits."}],
            "status": "completed",
        },
    ]

    class FakeClient:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.requests.append(params)
            if len(self.requests) == 1:
                return SimpleNamespace(
                    id="response-reasoning-tool-call",
                    output_text="",
                    output=[
                        *reasoning_items,
                        {
                            "type": "function_call",
                            "call_id": "call-reasoning",
                            "name": "edit_execute",
                            "arguments": '{"edits":[]}',
                        },
                    ],
                    status="completed",
                    usage=None,
                )

            return SimpleNamespace(
                id="response-after-tool",
                output_text="Done",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)
    config = _config(
        provider="openai",
        provider_kind="cloud",
        api_family="openai_responses",
        base_url="https://api.openai.com/v1",
        supports_streaming=False,
    )
    tools = [
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
    ]

    first = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(messages=[{"role": "user", "content": "Improve my resume."}]),
            tools,
        ),
    )
    assert first.provider_state == {"continuation_items": reasoning_items}
    tool_call = first.tool_calls[0]
    second = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(
                messages=[
                    {"role": "user", "content": "Improve my resume."},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.name,
                                    "arguments": tool_call.raw_arguments,
                                },
                            },
                        ],
                        "provider_state": first.provider_state,
                    },
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": '{"ok":true}',
                    },
                ]
            ),
            tools,
        ),
    )

    assert second.content == "Done"
    assert client.requests[0]["include"] == ["reasoning.encrypted_content"]
    assert client.requests[1]["input"] == [
        {"role": "user", "content": "Improve my resume."},
        *reasoning_items,
        {
            "type": "function_call",
            "call_id": "call-reasoning",
            "name": "edit_execute",
            "arguments": '{"edits":[]}',
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": "call-reasoning",
            "output": '{"ok":true}',
        },
    ]


def test_xai_responses_replays_encrypted_reasoning_across_tool_rounds(
    monkeypatch,
) -> None:
    first_reasoning_item = {
        "type": "reasoning",
        "id": "reasoning-xai-1",
        "encrypted_content": "opaque-xai-reasoning",
        "summary": [],
        "status": "completed",
    }
    second_reasoning_item = {
        "type": "reasoning",
        "id": "reasoning-xai-2",
        "encrypted_content": "opaque-xai-reasoning-2",
        "summary": [],
        "status": "completed",
    }

    class FakeClient:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.requests.append(params)
            if len(self.requests) == 1:
                return SimpleNamespace(
                    id="response-xai-tool-call",
                    output_text="",
                    output=[
                        first_reasoning_item,
                        {
                            "type": "function_call",
                            "call_id": "call-xai-reasoning",
                            "name": "resume_lookup",
                            "arguments": "{}",
                        },
                    ],
                    status="completed",
                    usage=None,
                )
            if len(self.requests) == 2:
                return SimpleNamespace(
                    id="response-xai-second-tool-call",
                    output_text="",
                    output=[
                        second_reasoning_item,
                        {
                            "type": "function_call",
                            "call_id": "call-xai-reasoning-2",
                            "name": "resume_lookup",
                            "arguments": "{}",
                        },
                    ],
                    status="completed",
                    usage=None,
                )
            return SimpleNamespace(
                id="response-xai-after-tool",
                output_text="Done",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)
    config = _config(
        provider="xai",
        provider_kind="cloud",
        api_family="openai_responses",
        base_url="https://api.x.ai/v1",
        supports_streaming=False,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "resume_lookup",
                "parameters": {"type": "object"},
            },
        },
    ]

    first = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(messages=[{"role": "user", "content": "Inspect my resume."}]),
            tools,
        ),
    )
    first_assistant = {
        "role": "assistant",
        "content": None,
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
        "provider_state": first.provider_state,
    }
    first_tool_result = {
        "role": "tool",
        "tool_call_id": first.tool_calls[0].id,
        "content": '{"ok":true}',
    }
    second = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(
                messages=[
                    {"role": "user", "content": "Inspect my resume."},
                    first_assistant,
                    first_tool_result,
                ]
            ),
            tools,
        ),
    )
    third = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(
                messages=[
                    {"role": "user", "content": "Inspect my resume."},
                    first_assistant,
                    first_tool_result,
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": second.tool_calls[0].id,
                                "type": "function",
                                "function": {
                                    "name": second.tool_calls[0].name,
                                    "arguments": second.tool_calls[0].raw_arguments,
                                },
                            },
                        ],
                        "provider_state": second.provider_state,
                    },
                    {
                        "role": "tool",
                        "tool_call_id": second.tool_calls[0].id,
                        "content": '{"ok":true}',
                    },
                ]
            ),
            tools,
        ),
    )

    assert third.content == "Done"
    assert client.requests[0]["store"] is False
    assert client.requests[0]["include"] == ["reasoning.encrypted_content"]
    assert client.requests[1]["include"] == ["reasoning.encrypted_content"]
    assert client.requests[2]["include"] == ["reasoning.encrypted_content"]
    assert client.requests[1]["input"][1] == first_reasoning_item
    assert client.requests[2]["input"][1] == first_reasoning_item
    assert client.requests[2]["input"][4] == second_reasoning_item


@pytest.mark.parametrize(
    ("provider", "provider_kind", "base_url"),
    [
        ("custom-cloud", "custom", "https://responses.example.test/v1"),
        ("openai", "cloud", "https://openai-proxy.example.test/v1"),
        ("xai", "cloud", "https://xai-proxy.example.test/v1"),
    ],
)
def test_non_official_responses_endpoint_does_not_receive_reasoning_include(
    monkeypatch,
    provider: str,
    provider_kind: str,
    base_url: str,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-custom-thinking",
                output_text="Done",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    asyncio.run(
        async_complete_chat(
            _config(
                provider=provider,
                provider_kind=provider_kind,
                api_family="openai_responses",
                base_url=base_url,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "Inspect my resume."}]),
        ),
    )

    assert client.params["store"] is False
    assert "include" not in client.params


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("openai", "https://api.openai.com/v1"),
        ("xai", "https://api.x.ai/v1"),
    ],
)
def test_official_responses_providers_request_encrypted_reasoning_under_auto(
    monkeypatch,
    provider: str,
    base_url: str,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **params: Any) -> object:
            self.params = params
            return SimpleNamespace(
                id="response-auto-reasoning",
                output_text="Done",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    asyncio.run(
        async_complete_chat(
            _config(
                provider=provider,
                provider_kind="cloud",
                api_family="openai_responses",
                base_url=base_url,
            ),
            LlmPrompt(messages=[{"role": "user", "content": "Inspect the resume."}]),
        ),
    )

    assert client.params["include"] == ["reasoning.encrypted_content"]
    assert "reasoning" not in client.params


@pytest.mark.parametrize(
    "provider_state",
    [
        {"thinking_blocks": []},
        {"continuation_items": []},
        {"continuation_items": ["not-an-item"]},
        {
            "continuation_items": [
                {
                    "type": "reasoning",
                    "id": "reasoning-1",
                    "encrypted_content": "opaque",
                    "summary": [],
                },
            ],
            "steps": [],
        },
        {
            "continuation_items": [
                {
                    "type": "message",
                    "id": "reasoning-1",
                    "encrypted_content": "opaque",
                    "summary": [],
                },
            ],
        },
        {
            "continuation_items": [
                {
                    "type": "reasoning",
                    "id": "",
                    "encrypted_content": "opaque",
                    "summary": [],
                },
            ],
        },
        {
            "continuation_items": [
                {
                    "type": "reasoning",
                    "id": "reasoning-1",
                    "encrypted_content": "",
                    "summary": [],
                },
            ],
        },
        {
            "continuation_items": [
                {
                    "type": "reasoning",
                    "id": "reasoning-1",
                    "encrypted_content": "opaque",
                    "summary": "not-a-list",
                },
            ],
        },
        {
            "continuation_items": [
                {
                    "type": "reasoning",
                    "id": "reasoning-1",
                    "encrypted_content": "opaque",
                    "summary": [],
                    "status": "unknown",
                },
            ],
        },
        {
            "continuation_items": [
                {
                    "type": "reasoning",
                    "id": "reasoning-1",
                    "encrypted_content": "opaque",
                    "summary": [],
                    "content": "not-a-list",
                },
            ],
        },
    ],
)
def test_openai_responses_rejects_malformed_reasoning_state_before_request(
    monkeypatch,
    provider_state: dict[str, Any],
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.called = False
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **_: Any) -> object:
            self.called = True
            return SimpleNamespace(
                id="unexpected-response",
                output_text="unexpected",
                output=[],
                status="completed",
                usage=None,
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_responses, "async_openai_client", lambda _: client)

    with pytest.raises(
        LlmRequestError,
        match="OpenAI Responses continuation state is invalid",
    ):
        asyncio.run(
            async_complete_chat(
                _config(
                    provider="openai",
                    provider_kind="cloud",
                    api_family="openai_responses",
                    supports_streaming=False,
                ),
                LlmPrompt(
                    messages=[
                        {"role": "user", "content": "First request."},
                        {
                            "role": "assistant",
                            "content": "First response.",
                            "provider_state": provider_state,
                        },
                        {"role": "user", "content": "Follow up."},
                    ]
                ),
            ),
        )

    assert client.called is False


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
                _config(
                    provider="openai",
                    provider_kind="cloud",
                    api_family="openai_responses",
                    base_url="https://api.openai.com/v1",
                ),
                LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
                request_context=LlmRequestContext(cache_key="resume-session-1"),
            ),
        ),
    )

    assert FakeResponses.create_params["stream"] is True
    assert FakeResponses.create_params["prompt_cache_key"] == "resume-session-1"
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
            LlmPrompt(messages=[{"role": "user", "content": "find project"}]),
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

    assert [tool_call.id for tool_call in message.tool_calls] == ["call-1"]
    assert message.validation_errors
    assert message.validation_errors[0].tool_call.id == "call-1"
    assert "required property" in message.validation_errors[0].message


def test_tool_argument_validation_preserves_each_mixed_batch_result(
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
            LlmPrompt(messages=[{"role": "user", "content": "find skills"}]),
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

    assert [tool_call.id for tool_call in message.tool_calls] == [
        "fc-valid",
        "fc-invalid",
    ]
    assert [error.tool_call.id for error in message.validation_errors] == [
        "fc-invalid",
    ]
    assert "required property" in message.validation_errors[0].message
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
        provider_kind="cloud",
        model="claude-test",
        base_url="https://api.anthropic.com/v1",
        api_family="anthropic_messages",
    )

    message = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "system text"},
                    {"role": "user", "content": "hello"},
                ]
            ),
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
    assert captured["payload"]["system"] == [
        {
            "type": "text",
            "text": "system text",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    assert captured["payload"]["cache_control"] == {"type": "ephemeral"}
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": "hello"},
    ]
    assert captured["payload"]["tools"][0]["input_schema"] == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    }
    assert "thinking" not in captured["payload"]
    assert captured["payload"]["temperature"] == 0.3
    assert captured["payload"]["top_p"] == 0.8
    assert message.content == "checking"
    assert message.stop_reason == "tool_calls"
    assert message.usage and message.usage.total_tokens == 10
    assert message.tool_calls[0].id == "toolu-1"
    assert message.tool_calls[0].arguments == {"query": "project"}


def test_anthropic_context_window_stop_is_normalized_as_length(monkeypatch) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "msg-context-limit",
            "stop_reason": "model_context_window_exceeded",
            "content": [{"type": "text", "text": "Partial"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    message = asyncio.run(
        async_complete_chat(
            _config(
                provider="anthropic",
                provider_kind="cloud",
                api_family="anthropic_messages",
                base_url="https://api.anthropic.com/v1",
            ),
            LlmPrompt(messages=[{"role": "user", "content": "Review."}]),
        ),
    )

    assert message.stop_reason == "length"


@pytest.mark.parametrize(
    ("invalid_id", "invalid_name"),
    [
        (None, "resume_lookup"),
        ("", "resume_lookup"),
        ("toolu-invalid", None),
        ("toolu-invalid", ""),
    ],
)
def test_anthropic_rejects_malformed_call_in_terminal_tool_batch(
    monkeypatch,
    invalid_id: str | None,
    invalid_name: str | None,
) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "msg-invalid-tool-batch",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu-valid",
                    "name": "resume_lookup",
                    "input": {},
                },
                {
                    "type": "tool_use",
                    "id": invalid_id,
                    "name": invalid_name,
                    "input": {},
                },
            ],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    with pytest.raises(LlmRequestError, match="invalid tool use batch"):
        asyncio.run(
            async_complete_tool_call(
                _config(
                    provider="anthropic",
                    provider_kind="cloud",
                    api_family="anthropic_messages",
                    supports_streaming=False,
                ),
                LlmPrompt(messages=[{"role": "user", "content": "Inspect my resume."}]),
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


def test_anthropic_adapter_marks_static_prompt_prefixes_for_caching(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-cache-prefixes",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_tool_call(
            _config(
                provider="anthropic",
                provider_kind="cloud",
                base_url="https://api.anthropic.com/v1",
                api_family="anthropic_messages",
            ),
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "stable system instructions"},
                    {"role": "user", "content": "hello"},
                ]
            ),
            [
                {
                    "type": "function",
                    "function": {
                        "name": "resume_lookup",
                        "parameters": {"type": "object"},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "second_tool",
                        "parameters": {"type": "object"},
                    },
                },
            ],
        ),
    )

    assert captured["payload"]["system"] == [
        {
            "type": "text",
            "text": "stable system instructions",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    assert "cache_control" not in captured["payload"]["tools"][0]
    assert captured["payload"]["tools"][1]["cache_control"] == {
        "type": "ephemeral",
    }


def test_anthropic_adapter_enables_automatic_growing_conversation_cache(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-cache-conversation",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_chat(
            _config(
                provider="anthropic",
                provider_kind="cloud",
                base_url="https://api.anthropic.com/v1",
                api_family="anthropic_messages",
            ),
            LlmPrompt(
                messages=[
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": "first answer"},
                    {"role": "user", "content": "follow-up question"},
                ]
            ),
        ),
    )

    assert captured["payload"]["cache_control"] == {"type": "ephemeral"}
    assert captured["payload"]["messages"][-1] == {
        "role": "user",
        "content": "follow-up question",
    }


def test_anthropic_automatic_cache_advances_through_tool_results(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-cache-tool-result",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_tool_call(
            _config(
                provider="anthropic",
                provider_kind="cloud",
                base_url="https://api.anthropic.com/v1",
                api_family="anthropic_messages",
            ),
            LlmPrompt(
                messages=[
                    {"role": "user", "content": "inspect my resume"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "toolu-cache",
                                "type": "function",
                                "function": {
                                    "name": "resume_lookup",
                                    "arguments": '{"query":"skills"}',
                                },
                            },
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "toolu-cache",
                        "content": '{"matches":["Python"]}',
                    },
                ]
            ),
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

    assert captured["payload"]["cache_control"] == {"type": "ephemeral"}
    assert captured["payload"]["messages"][-1]["content"][-1] == {
        "type": "tool_result",
        "tool_use_id": "toolu-cache",
        "content": '{"matches":["Python"]}',
    }


@pytest.mark.parametrize("provider_kind", ["custom", "cloud"])
def test_non_official_anthropic_endpoint_does_not_receive_cache_control(
    monkeypatch,
    provider_kind: str,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_post_json(_: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "msg-custom-anthropic",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    asyncio.run(
        async_complete_tool_call(
            _config(
                provider="anthropic",
                provider_kind=provider_kind,
                base_url="https://anthropic-compatible.example.test/v1",
                api_family="anthropic_messages",
                model="claude-sonnet-4-6",
                thinking_control="native_auto",
            ),
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "stable instructions"},
                    {"role": "user", "content": "inspect my resume"},
                ]
            ),
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

    assert captured["payload"]["system"] == "stable instructions"
    assert "cache_control" not in captured["payload"]
    assert "cache_control" not in captured["payload"]["messages"][-1]["content"][0]
    assert "cache_control" not in captured["payload"]["tools"][-1]
    assert "thinking" not in captured["payload"]


def test_anthropic_adapter_normalizes_prompt_cache_usage(monkeypatch) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "msg-cache-usage",
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 5,
                "cache_creation_input_tokens": 40,
                "cache_read_input_tokens": 60,
                "output_tokens": 7,
                "output_tokens_details": {"thinking_tokens": 3},
            },
            "content": [{"type": "text", "text": "Done"}],
        }

    monkeypatch.setattr(anthropic_messages, "async_post_json", fake_post_json)

    message = asyncio.run(
        async_complete_chat(
            _config(
                provider="anthropic",
                provider_kind="cloud",
                base_url="https://api.anthropic.com/v1",
                api_family="anthropic_messages",
            ),
            LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
        ),
    )

    assert message.usage
    assert message.usage.input_tokens == 105
    assert message.usage.cached_input_tokens == 60
    assert message.usage.cache_write_input_tokens == 40
    assert message.usage.output_tokens == 7
    assert message.usage.total_tokens == 112
    assert message.usage.reasoning_tokens == 3


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
        provider_kind="cloud",
        model="claude-thinking",
        base_url="https://api.anthropic.com/v1",
        api_family="anthropic_messages",
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
            LlmPrompt(messages=[{"role": "user", "content": "Inspect my project."}]),
            tools,
        ),
    )
    assert first.reasoning == "I should inspect the resume."
    assert first.provider_state == {
        "model": "claude-thinking",
        "content_blocks": [
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

    second = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(
                messages=[
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
                ]
            ),
            tools,
        ),
    )

    assert second.content == "Done"
    assert all("thinking" not in payload for payload in captured_payloads)
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
                    "usage": {
                        "input_tokens": 4,
                        "cache_creation_input_tokens": 5,
                        "cache_read_input_tokens": 3,
                    },
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
                    provider_kind="cloud",
                    base_url="https://api.anthropic.com/v1",
                    api_family="anthropic_messages",
                ),
                LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
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
        "model": "gpt-test",
        "content_blocks": [
            {
                "type": "thinking",
                "thinking": "think ",
                "signature": "stream-signature",
            },
            {"type": "text", "text": "Hello"},
        ],
    }
    assert events[-1].message.usage
    assert events[-1].message.usage.input_tokens == 12
    assert events[-1].message.usage.cached_input_tokens == 3
    assert events[-1].message.usage.cache_write_input_tokens == 5
    assert events[-1].message.usage.total_tokens == 14

    _, replayed = anthropic_messages.anthropic_messages(
        [
            {
                "role": "assistant",
                "content": events[-1].message.content,
                "provider_state": events[-1].message.provider_state,
            },
        ],
        model="gpt-test",
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
                    "type": "text",
                    "text": "Hello",
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
            "usage": {
                "total_input_tokens": 6,
                "total_output_tokens": 3,
                "total_tokens": 9,
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
        base_url="https://generativelanguage.googleapis.com/v1",
        api_family="google_gemini",
        temperature=None,
        top_p=None,
    )

    message = asyncio.run(
        async_complete_tool_call(
            config,
            LlmPrompt(
                messages=[
                    {"role": "system", "content": "system text"},
                    {"role": "user", "content": "hello"},
                ]
            ),
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
        "https://generativelanguage.googleapis.com/v1/interactions"
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
    assert captured["payload"]["tools"] == [
        {
            "type": "function",
            "name": "resume_lookup",
            "description": "Lookup resume",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    ]
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
                "content": "I will inspect the resume.",
                "provider_state": {
                    "steps": [
                        {
                            "type": "thought",
                            "text": "Need resume context.",
                        },
                        {
                            "type": "model_output",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "I will inspect the resume.",
                                },
                            ],
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
            "type": "model_output",
            "content": [
                {"type": "text", "text": "I will inspect the resume."},
            ],
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


def test_gemini_payload_replays_plain_assistant_text_in_order() -> None:
    payload = google_gemini.gemini_payload(
        _config(api_family="google_gemini"),
        [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "follow-up question"},
        ],
    )

    assert payload["input"] == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "first question"}],
        },
        {
            "type": "model_output",
            "content": [{"type": "text", "text": "first answer"}],
        },
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "follow-up question"}],
        },
    ]


def test_gemini_replays_all_provider_steps_once_and_in_order(monkeypatch) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "gemini-text-history",
            "status": "completed",
            "steps": [
                {
                    "type": "thought",
                    "summary": [{"type": "text", "text": "Consider context."}],
                },
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "First answer."}],
                },
            ],
        }

    monkeypatch.setattr(google_gemini, "async_post_json", fake_post_json)

    message = asyncio.run(
        google_gemini.complete(
            _config(api_family="google_gemini"),
            [{"role": "user", "content": "first question"}],
        ),
    )
    replay = google_gemini.gemini_input(
        [
            {"role": "user", "content": "first question"},
            {
                "role": "assistant",
                "content": message.content,
                "provider_state": message.provider_state,
            },
            {"role": "user", "content": "follow-up question"},
        ],
    )

    assert message.provider_state == {
        "steps": [
            {
                "type": "thought",
                "summary": [{"type": "text", "text": "Consider context."}],
            },
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "First answer."}],
            },
        ],
    }
    assert replay == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "first question"}],
        },
        {
            "type": "thought",
            "summary": [{"type": "text", "text": "Consider context."}],
        },
        {
            "type": "model_output",
            "content": [{"type": "text", "text": "First answer."}],
        },
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "follow-up question"}],
        },
    ]


def test_gemini_replays_cross_provider_assistant_without_gemini_state() -> None:
    payload = google_gemini.gemini_payload(
        _config(api_family="google_gemini"),
        [
            {"role": "user", "content": "find skills"},
            {
                "role": "assistant",
                "content": "I will inspect the resume.",
                "provider_state": {
                    "thinking_blocks": [
                        {"type": "thinking", "thinking": "Inspect context."},
                    ],
                },
                "tool_calls": [
                    {
                        "id": "cross-provider-call",
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "arguments": '{"query":"skills"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "cross-provider-call",
                "content": '{"matches":["Python"]}',
            },
        ],
    )

    assert payload["input"] == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "find skills"}],
        },
        {
            "type": "model_output",
            "content": [
                {"type": "text", "text": "I will inspect the resume."},
            ],
        },
        {
            "type": "function_call",
            "id": "cross-provider-call",
            "name": "resume_lookup",
            "arguments": {"query": "skills"},
        },
        {
            "type": "function_result",
            "name": "resume_lookup",
            "call_id": "cross-provider-call",
            "result": [{"type": "text", "text": '{"matches":["Python"]}'}],
        },
    ]


def test_gemini_unary_tool_call_drops_tools_from_incomplete_status(
    monkeypatch,
) -> None:
    async def fake_post_json(_: str, **__: Any) -> dict[str, Any]:
        return {
            "id": "gemini-unary-incomplete",
            "status": "incomplete",
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


def test_gemini_v1_unary_rejects_completed_function_call(
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

    with pytest.raises(LlmRequestError, match="invalid terminal status"):
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


def test_gemini_v1_stream_completes_on_authoritative_completed_event(
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
                "event_type": "step.start",
                "index": 0,
                "step": {
                    "type": "model_output",
                    "content": [{"type": "text", "text": "He"}],
                },
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
                "delta": {"type": "text", "text": "l"},
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
                    base_url="https://generativelanguage.googleapis.com/v1",
                    api_family="google_gemini",
                ),
                LlmPrompt(messages=[{"role": "user", "content": "hello"}]),
            ),
        ),
    )

    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1/interactions"
    )
    assert captured["headers"]["Accept"] == "text/event-stream"
    assert captured["payload"]["stream"] is True
    assert [(event.type, event.delta) for event in events] == [
        ("activity", ""),
        ("activity", ""),
        ("text_delta", "He"),
        ("text_delta", "l"),
        ("text_delta", "lo"),
        ("activity", ""),
        ("done", ""),
    ]
    assert events[-1].type == "done"
    assert events[-1].message
    assert events[-1].message.content == "Hello"
    assert events[-1].message.usage and events[-1].message.usage.total_tokens == 5
    assert events[-1].message.provider_state == {
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "Hello"}],
            },
        ],
    }


def test_gemini_v1_tool_stream_buffers_arguments_until_completed_action(
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
                "event_type": "interaction.status_update",
                "interaction_id": "gemini-tool-stream",
                "status": "in_progress",
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
                "delta": {
                    "type": "arguments_delta",
                    "arguments": '{"query":',
                },
            },
            {
                "event_type": "step.delta",
                "index": 5,
                "delta": {
                    "type": "arguments_delta",
                    "arguments": '"skill',
                },
            },
            {
                "event_type": "step.delta",
                "index": 5,
                "delta": {"type": "arguments_delta", "arguments": 's"}'},
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
                    base_url=("https://generativelanguage.googleapis.com/v1"),
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
        ("activity", ""),
        ("reasoning_delta", "Need resume context."),
        ("activity", ""),
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


def test_gemini_v1_tool_stream_rejects_completed_function_call(
    monkeypatch,
) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {
                    "type": "function_call",
                    "id": "fc-mismatched-terminal",
                    "name": "resume_lookup",
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
                    "id": "gemini-mismatched-terminal",
                    "status": "completed",
                },
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="invalid terminal status"):
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


def test_gemini_tool_stream_rejects_eof_before_terminal_event(monkeypatch) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {
                    "type": "function_call",
                    "id": "fc-no-terminal",
                    "name": "resume_lookup",
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


def test_gemini_v1_stream_error_discards_provider_message(monkeypatch) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        yield {
            "event_type": "error",
            "error": {
                "code": "internal",
                "message": "provider debug secret must not escape",
            },
        }

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError) as exc_info:
        asyncio.run(
            _collect_stream(
                google_gemini.stream(
                    _config(api_family="google_gemini"),
                    [{"role": "user", "content": "hello"}],
                ),
            ),
        )

    assert str(exc_info.value) == "Model provider stream failed."


def test_gemini_tool_stream_rejects_incomplete_arguments_at_completed_action(
    monkeypatch,
) -> None:
    async def fake_stream_json(_: str, **__: Any) -> Any:
        for event in [
            {
                "event_type": "step.start",
                "index": 0,
                "step": {
                    "type": "function_call",
                    "id": "fc-partial",
                    "name": "resume_lookup",
                },
            },
            {
                "event_type": "step.delta",
                "index": 0,
                "delta": {
                    "type": "arguments_delta",
                    "arguments": '{"query":"skills"',
                },
            },
            {"event_type": "step.stop", "index": 0},
            {
                "event_type": "interaction.completed",
                "interaction": {
                    "id": "gemini-partial",
                    "status": "requires_action",
                },
            },
        ]:
            yield event

    monkeypatch.setattr(google_gemini, "async_stream_json", fake_stream_json)

    with pytest.raises(LlmRequestError, match="invalid function call arguments"):
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
