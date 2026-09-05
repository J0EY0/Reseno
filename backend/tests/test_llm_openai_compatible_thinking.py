from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from openai.types.chat import ChatCompletionChunk

from app.services.llm.adapters import openai_chat
from app.services.llm.adapters.openai_chat import _tool_completion_params
from app.services.llm.common import chat_completion_params, openai_chat_messages
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import AgentLlmConfig, LlmPrompt


def _config(**overrides: Any) -> AgentLlmConfig:
    values: dict[str, Any] = {
        "client_id": "compatible-thinking-test",
        "name": "Compatible Thinking Test",
        "provider": "qwen",
        "provider_kind": "cloud",
        "api_family": "openai_compatible_chat",
        "model": "discovered-thinking-model",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "secret",
        "temperature": None,
        "top_p": None,
        "max_tokens": None,
        "timeout_seconds": 60,
        "thinking_control": "native_auto",
    }
    values.update(overrides)
    return AgentLlmConfig(**values)


def _prompt() -> LlmPrompt:
    return LlmPrompt(messages=[{"role": "user", "content": "Review my resume."}])


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "resume_lookup",
                "parameters": {"type": "object"},
            },
        },
    ]


class _Stream:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self.chunks = chunks

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> ChatCompletionChunk:
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)

    async def aclose(self) -> None:
        return None


def _chunk(
    delta: dict[str, Any],
    *,
    finish_reason: str | None = None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "minimax-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "discovered-thinking-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "delta": delta,
                },
            ],
        },
    )


def test_official_qwen_native_auto_enables_thinking_without_an_effort_tier() -> None:
    params = chat_completion_params(_config(), _prompt(), stream=True)

    assert params["extra_body"] == {"enable_thinking": True}
    assert "reasoning_effort" not in params


def test_official_qwen_native_off_explicitly_disables_thinking() -> None:
    params = chat_completion_params(
        _config(thinking_control="native_off"),
        _prompt(),
        stream=True,
    )

    assert params["extra_body"] == {"enable_thinking": False}
    assert "reasoning_effort" not in params


def test_official_qwen_thinking_keeps_explicit_prompt_cache_boundaries() -> None:
    params = chat_completion_params(
        _config(model="qwen3.7-plus"),
        LlmPrompt(
            messages=[
                {"role": "system", "content": "Stable instructions."},
                {"role": "user", "content": "Current resume."},
            ],
            stable_prefix_message_counts=(1,),
        ),
        stream=True,
    )

    assert params["extra_body"] == {"enable_thinking": True}
    assert params["messages"][0]["content"] == [
        {
            "type": "text",
            "text": "Stable instructions.",
            "cache_control": {"type": "ephemeral"},
        },
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        {"thinking_control": "provider_default"},
        {"provider_kind": "custom"},
        {"api_family": "openai_responses"},
        {"base_url": "https://qwen-compatible.example.test/v1"},
    ],
)
def test_qwen_thinking_control_is_omitted_without_the_verified_native_target(
    overrides: dict[str, Any],
) -> None:
    params = chat_completion_params(
        _config(**overrides),
        _prompt(),
        stream=True,
    )

    assert "extra_body" not in params
    assert "reasoning_effort" not in params


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_kind": "custom"},
        {"api_family": "openai_responses"},
        {"base_url": "https://qwen-compatible.example.test/v1"},
    ],
)
def test_qwen_native_off_fails_closed_for_an_unverified_compatible_target(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(
        LlmRequestError,
        match="Thinking Off is unavailable for this model configuration",
    ):
        chat_completion_params(
            _config(thinking_control="native_off", **overrides),
            _prompt(),
            stream=True,
        )


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        ("deepseek", "https://api.deepseek.com"),
        ("glm", "https://open.bigmodel.cn/api/paas/v4"),
    ],
)
def test_official_compatible_native_off_uses_the_disabled_thinking_object(
    provider: str,
    base_url: str,
) -> None:
    params = chat_completion_params(
        _config(
            provider=provider,
            base_url=base_url,
            thinking_control="native_off",
        ),
        _prompt(),
        stream=True,
    )

    assert params["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in params


@pytest.mark.parametrize("provider", ["deepseek", "glm", "moonshot"])
def test_compatible_native_off_fails_closed_for_an_unverified_target(
    provider: str,
) -> None:
    base_url = (
        "https://api.moonshot.ai/v1"
        if provider == "moonshot"
        else "https://compatible.example.test/v1"
    )
    with pytest.raises(
        LlmRequestError,
        match="Thinking Off is unavailable for this model configuration",
    ):
        chat_completion_params(
            _config(
                provider=provider,
                base_url=base_url,
                thinking_control="native_off",
            ),
            _prompt(),
            stream=True,
        )


@pytest.mark.parametrize(
    ("provider", "extra_body"),
    [
        ("vllm", {"chat_template_kwargs": {"enable_thinking": True}}),
        ("sglang", {"reasoning": {"enabled": True}}),
    ],
)
def test_registered_local_runtime_projects_native_auto_without_a_model_table(
    provider: str,
    extra_body: dict[str, Any],
) -> None:
    params = chat_completion_params(
        _config(
            provider=provider,
            provider_kind="local",
            base_url="http://inference.lan:9000/v1",
        ),
        _prompt(),
        stream=True,
    )

    assert params["extra_body"] == extra_body
    assert "reasoning_effort" not in params


@pytest.mark.parametrize("provider", ["vllm", "sglang"])
@pytest.mark.parametrize("thinking_control", ["none", "provider_default"])
def test_local_runtime_omits_thinking_when_auto_was_not_selected(
    provider: str,
    thinking_control: str,
) -> None:
    params = chat_completion_params(
        _config(
            provider=provider,
            provider_kind="local",
            base_url="http://inference.lan:9000/v1",
            thinking_control=thinking_control,
        ),
        _prompt(),
        stream=True,
    )

    assert "extra_body" not in params


def test_official_deepseek_native_auto_registers_tools_without_tool_choice() -> None:
    params = _tool_completion_params(
        _config(
            provider="deepseek",
            base_url="https://api.deepseek.com",
        ),
        _prompt(),
        _tools(),
    )

    assert params["tools"]
    assert "extra_body" not in params
    assert "tool_choice" not in params


def test_official_deepseek_provider_default_also_omits_rejected_tool_choice() -> None:
    params = _tool_completion_params(
        _config(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            thinking_control="provider_default",
        ),
        _prompt(),
        _tools(),
    )

    assert params["tools"]
    assert "tool_choice" not in params


@pytest.mark.parametrize(
    "overrides",
    [
        {"thinking_control": "none"},
        {
            "thinking_control": "native_off",
            "base_url": "https://api.deepseek.com",
        },
        {"provider_kind": "custom"},
        {"base_url": "https://deepseek-compatible.example.test/v1"},
    ],
)
def test_deepseek_tool_choice_omission_is_strictly_guarded(
    overrides: dict[str, Any],
) -> None:
    params = _tool_completion_params(
        _config(provider="deepseek", **overrides),
        _prompt(),
        _tools(),
    )

    assert params["tool_choice"] == "auto"


@pytest.mark.parametrize(
    ("provider", "provider_kind", "base_url"),
    [
        ("qwen", "cloud", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("vllm", "local", "http://inference.lan:9000/v1"),
        ("sglang", "local", "http://inference.lan:9000/v1"),
    ],
)
def test_other_compatible_tools_keep_auto_selection_enabled(
    provider: str,
    provider_kind: str,
    base_url: str,
) -> None:
    params = _tool_completion_params(
        _config(
            provider=provider,
            provider_kind=provider_kind,
            base_url=base_url,
        ),
        _prompt(),
        _tools(),
    )

    assert params["tools"]
    assert params["tool_choice"] == "auto"


def test_official_deepseek_tool_turn_replays_reasoning_with_non_null_content() -> None:
    messages = openai_chat_messages(
        [
            {"role": "user", "content": "Inspect my projects."},
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "I need the project details.",
                "tool_calls": [
                    {
                        "id": "call-projects",
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "arguments": '{"section":"projects"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-projects",
                "content": '{"projects":["ResuMate"]}',
            },
        ],
        config=_config(
            provider="deepseek",
            base_url="https://api.deepseek.com",
        ),
    )

    assert messages[1]["reasoning_content"] == "I need the project details."
    assert messages[1]["content"] == ""
    assert messages[1]["tool_calls"][0]["id"] == "call-projects"


def test_official_deepseek_tool_turn_never_sends_null_assistant_content() -> None:
    messages = openai_chat_messages(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-projects",
                        "type": "function",
                        "function": {
                            "name": "resume_lookup",
                            "arguments": "{}",
                        },
                    },
                ],
            },
        ],
        config=_config(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            thinking_control="provider_default",
        ),
    )

    assert messages[0]["content"] == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"thinking_control": "none"},
        {
            "thinking_control": "native_off",
            "base_url": "https://api.deepseek.com",
        },
        {"provider_kind": "custom"},
        {"base_url": "https://deepseek-compatible.example.test/v1"},
    ],
)
def test_deepseek_continuation_projection_is_guarded(
    overrides: dict[str, Any],
) -> None:
    source = [
        {
            "role": "assistant",
            "content": None,
            "reasoning_content": "private continuation",
            "tool_calls": [],
        },
    ]

    assert (
        openai_chat_messages(
            source,
            config=_config(provider="deepseek", **overrides),
        )
        == source
    )


@pytest.mark.parametrize("thinking_control", ["none", "native_auto"])
def test_official_minimax_splits_reasoning_from_visible_content_even_without_discovery(
    monkeypatch: pytest.MonkeyPatch,
    thinking_control: str,
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
                id="minimax-response",
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        message=SimpleNamespace(
                            content="I'll inspect the resume.",
                            reasoning_details=[
                                {"type": "reasoning.text", "text": "Plan A."},
                                {
                                    "type": "reasoning.text",
                                    "text": "Plan B.",
                                    "signature": "signed-b",
                                },
                            ],
                            tool_calls=[
                                SimpleNamespace(
                                    id="call-minimax",
                                    function=SimpleNamespace(
                                        name="resume_lookup",
                                        arguments='{"section":"summary"}',
                                    ),
                                ),
                            ],
                        ),
                    ),
                ],
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    message = asyncio.run(
        openai_chat.complete_tool_call(
            _config(
                provider="minimax",
                base_url="https://api.minimaxi.com/v1",
                thinking_control=thinking_control,
            ),
            _prompt(),
            _tools(),
        ),
    )

    assert client.params["extra_body"] == {"reasoning_split": True}
    assert message.content == "I'll inspect the resume."
    assert message.reasoning == "Plan A.Plan B."
    assert message.provider_state == {
        "model": "discovered-thinking-model",
        "reasoning_details": [
            {"type": "reasoning.text", "text": "Plan A."},
            {
                "type": "reasoning.text",
                "text": "Plan B.",
                "signature": "signed-b",
            },
        ],
    }


@pytest.mark.parametrize("thinking_control", ["none", "provider_default"])
def test_official_minimax_always_requests_reasoning_split(
    thinking_control: str,
) -> None:
    params = chat_completion_params(
        _config(
            provider="minimax",
            base_url="https://api.minimaxi.com/v1",
            thinking_control=thinking_control,
        ),
        _prompt(),
        stream=True,
    )

    assert params["extra_body"] == {"reasoning_split": True}


@pytest.mark.parametrize(
    ("thinking_control", "expected_thinking"),
    [
        ("none", None),
        ("native_auto", {"type": "adaptive"}),
        ("native_off", {"type": "disabled"}),
        ("provider_default", None),
    ],
)
def test_official_minimax_m3_projects_its_native_thinking_control(
    thinking_control: str,
    expected_thinking: dict[str, str] | None,
) -> None:
    params = chat_completion_params(
        _config(
            provider="minimax",
            model="MiniMax-M3",
            base_url="https://api.minimaxi.com/v1",
            thinking_control=thinking_control,
        ),
        _prompt(),
        stream=True,
    )

    expected = {"reasoning_split": True}
    if expected_thinking is not None:
        expected["thinking"] = expected_thinking
    assert params["extra_body"] == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_kind": "custom"},
        {"api_family": "openai_responses"},
        {"base_url": "https://minimax-compatible.example.test/v1"},
    ],
)
def test_minimax_reasoning_split_is_guarded(
    overrides: dict[str, Any],
) -> None:
    params = chat_completion_params(
        _config(provider="minimax", **overrides),
        _prompt(),
        stream=True,
    )

    assert "extra_body" not in params


def test_official_minimax_tool_stream_keeps_ordered_split_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.params: dict[str, Any] = {}
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **params: Any) -> _Stream:
            self.params = params
            return _Stream(
                [
                    _chunk(
                        {
                            "reasoning_details": [
                                {"type": "reasoning.text", "text": "Plan"},
                            ],
                        },
                    ),
                    _chunk(
                        {
                            "reasoning_details": [
                                {"type": "reasoning.text", "text": "Plan"},
                            ],
                        },
                    ),
                    _chunk(
                        {
                            "reasoning_details": [
                                {"type": "reasoning.text", "text": "Plan A."},
                                {
                                    "type": "reasoning.text",
                                    "text": "Plan B.",
                                    "signature": "signed-b",
                                },
                            ],
                        },
                    ),
                    _chunk(
                        {
                            "content": "Checking.",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-minimax",
                                    "type": "function",
                                    "function": {
                                        "name": "resume_lookup",
                                        "arguments": '{"section":"summary"}',
                                    },
                                },
                            ],
                        },
                    ),
                    _chunk({}, finish_reason="tool_calls"),
                ],
            )

        async def close(self) -> None:
            return None

    client = FakeClient()
    monkeypatch.setattr(openai_chat, "async_openai_client", lambda _: client)

    async def collect() -> list[Any]:
        return [
            event
            async for event in openai_chat.stream_tool_call(
                _config(
                    provider="minimax",
                    base_url="https://api.minimaxi.com/v1",
                ),
                _prompt(),
                _tools(),
            )
        ]

    events = asyncio.run(collect())

    assert client.params["extra_body"] == {"reasoning_split": True}
    assert [(event.type, event.delta) for event in events[:-1]] == [
        ("reasoning_delta", "Plan"),
        ("activity", ""),
        ("reasoning_delta", " A.Plan B."),
        ("text_delta", "Checking."),
        ("activity", ""),
    ]
    message = events[-1].message
    assert message is not None
    assert message.content == "Checking."
    assert message.reasoning == "Plan A.Plan B."
    assert message.provider_state == {
        "model": "discovered-thinking-model",
        "reasoning_details": [
            {"type": "reasoning.text", "text": "Plan A."},
            {
                "type": "reasoning.text",
                "text": "Plan B.",
                "signature": "signed-b",
            },
        ],
    }


def test_official_minimax_text_stream_emits_split_reasoning_without_think_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create),
            )

        async def create(self, **_: Any) -> _Stream:
            return _Stream(
                [
                    _chunk(
                        {
                            "reasoning_details": [
                                {"type": "reasoning.text", "text": "Private"},
                            ],
                        },
                    ),
                    _chunk(
                        {
                            "reasoning_details": [
                                {
                                    "type": "reasoning.text",
                                    "text": "Private reasoning.",
                                },
                            ],
                        },
                    ),
                    _chunk({"content": "Visible answer."}),
                    _chunk({}, finish_reason="stop"),
                ],
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        openai_chat,
        "async_openai_client",
        lambda _: FakeClient(),
    )

    async def collect() -> list[Any]:
        return [
            event
            async for event in openai_chat.stream(
                _config(
                    provider="minimax",
                    base_url="https://api.minimaxi.com/v1",
                ),
                _prompt(),
            )
        ]

    events = asyncio.run(collect())

    assert [(event.type, event.delta) for event in events[:-1]] == [
        ("reasoning_delta", "Private"),
        ("reasoning_delta", " reasoning."),
        ("text_delta", "Visible answer."),
    ]
    message = events[-1].message
    assert message is not None
    assert message.reasoning == "Private reasoning."
    assert message.content == "Visible answer."
    assert "<think>" not in message.content


def test_official_minimax_tool_turn_replays_ordered_reasoning_details() -> None:
    params = chat_completion_params(
        _config(
            provider="minimax",
            base_url="https://api.minimaxi.com/v1",
        ),
        LlmPrompt(
            messages=[
                {"role": "user", "content": "Inspect."},
                {
                    "role": "assistant",
                    "content": "Checking.",
                    "tool_calls": [],
                    "provider_state": {
                        "model": "discovered-thinking-model",
                        "reasoning_details": [
                            {"type": "reasoning.text", "text": "First."},
                            {"type": "reasoning.text", "text": "Second."},
                        ],
                    },
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "{}"},
            ],
        ),
        stream=False,
    )

    assert params["messages"][1] == {
        "role": "assistant",
        "content": "Checking.",
        "tool_calls": [],
        "reasoning_details": [
            {"type": "reasoning.text", "text": "First."},
            {"type": "reasoning.text", "text": "Second."},
        ],
    }


@pytest.mark.parametrize(
    "state",
    [
        {
            "model": "other-model",
            "reasoning_details": [{"type": "reasoning.text", "text": "leak"}],
        },
        {"model": "discovered-thinking-model", "reasoning_details": "invalid"},
        {
            "model": "discovered-thinking-model",
            "reasoning_details": [{"type": "reasoning.text", "text": 7}],
        },
    ],
)
def test_minimax_invalid_or_cross_model_reasoning_state_fails_closed(
    state: dict[str, Any],
) -> None:
    with pytest.raises(LlmRequestError, match="continuation state is invalid"):
        chat_completion_params(
            _config(
                provider="minimax",
                base_url="https://api.minimaxi.com/v1",
            ),
            LlmPrompt(
                messages=[
                    {
                        "role": "assistant",
                        "content": "Visible",
                        "provider_state": state,
                    },
                ],
            ),
            stream=False,
        )
