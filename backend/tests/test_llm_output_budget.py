import asyncio
from collections.abc import AsyncIterator
from types import ModuleType

import pytest

from app.services.llm import (
    LlmAssistantMessage,
    LlmRequestError,
    LlmStreamEvent,
    async_complete_chat,
    async_stream_chat,
    async_stream_tool_call,
)
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
    openai_chat,
    openai_responses,
)
from app.services.llm.common import chat_completion_params
from app.services.llm.output_budget import (
    CONTEXT_COMPACTION_HEADROOM_TOKENS,
    compaction_headroom_tokens,
    estimate_prompt_tokens,
    resolve_request_output_budget,
)
from app.services.llm.types import AgentLlmConfig, LlmPrompt


async def _collect_events(
    stream: AsyncIterator[LlmStreamEvent],
) -> list[LlmStreamEvent]:
    return [event async for event in stream]


def _config(**overrides: object) -> AgentLlmConfig:
    values: dict[str, object] = {
        "client_id": "budget-test",
        "name": "Budget test",
        "provider": "openai",
        "provider_kind": "cloud",
        "api_family": "openai_responses",
        "model": "reasoning-model",
        "base_url": "https://api.openai.com/v1",
        "api_key": "test-key",
        "temperature": None,
        "top_p": None,
        "max_tokens": None,
        "timeout_seconds": 60,
        "context_window_tokens": 128_000,
        "model_max_output_tokens": 64_000,
    }
    values.update(overrides)
    return AgentLlmConfig(**values)  # type: ignore[arg-type]


def test_cloud_auto_omits_the_optional_provider_output_limit() -> None:
    prompt = LlmPrompt(messages=[{"role": "user", "content": "Improve my resume."}])
    config = _config(
        provider="minimax",
        api_family="openai_compatible_chat",
        model="MiniMax-M3",
        base_url="https://api.minimaxi.com/v1",
        model_max_output_tokens=128_000,
    )

    request_config = resolve_request_output_budget(config, prompt)

    assert request_config.max_tokens is None
    assert request_config.model_max_output_tokens == 128_000
    assert request_config.request_max_output_tokens is None
    assert "max_tokens" not in chat_completion_params(
        request_config,
        prompt,
        stream=False,
    )


def test_independent_input_ceiling_preserves_output_within_the_total_window() -> None:
    config = _config(
        context_window_tokens=272_000,
        shared_context_window_tokens=400_000,
        max_tokens=128_000,
        model_max_output_tokens=128_000,
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "x" * 1_000_000}])

    resolved = resolve_request_output_budget(config, prompt)

    assert estimate_prompt_tokens(prompt) < 272_000 - 4_096
    assert resolved.request_max_output_tokens == 128_000


@pytest.mark.parametrize(
    ("capability", "expected"),
    [(128_000, 16_000), (8_192, 8_192)],
)
def test_anthropic_auto_uses_its_mandatory_bounded_output_limit(
    capability: int,
    expected: int,
) -> None:
    config = _config(
        provider="anthropic",
        api_family="anthropic_messages",
        model_max_output_tokens=capability,
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "Review."}])

    resolved = resolve_request_output_budget(config, prompt)

    assert resolved.request_max_output_tokens == expected


def test_request_budget_rejects_input_beyond_the_model_input_ceiling() -> None:
    config = _config(context_window_tokens=8_000)
    prompt = LlmPrompt(messages=[{"role": "user", "content": "x" * 32_000}])

    with pytest.raises(LlmRequestError, match="input context"):
        resolve_request_output_budget(config, prompt)


@pytest.mark.parametrize("provider_kind", ["local", "custom"])
def test_manual_shared_context_dynamically_clamps_the_output_limit(
    provider_kind: str,
) -> None:
    config = _config(
        provider="ollama",
        provider_kind=provider_kind,
        api_family="openai_compatible_chat",
        context_window_tokens=32_000,
        max_tokens=32_000,
        model_max_output_tokens=None,
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "x" * 48_000}])

    resolved = resolve_request_output_budget(config, prompt)

    assert resolved.request_max_output_tokens == (
        32_000 - estimate_prompt_tokens(prompt) - 320
    )


def test_small_local_context_keeps_room_for_a_real_request() -> None:
    config = _config(
        provider="ollama",
        provider_kind="local",
        api_family="openai_compatible_chat",
        context_window_tokens=4_096,
        max_tokens=None,
        model_max_output_tokens=None,
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "Review."}])

    resolved = resolve_request_output_budget(config, prompt)

    assert resolved.request_max_output_tokens is not None
    assert resolved.request_max_output_tokens > 3_000


def test_history_compaction_reserve_is_independent_from_model_maximum() -> None:
    config = _config(model_max_output_tokens=64_000)

    assert compaction_headroom_tokens(config) == CONTEXT_COMPACTION_HEADROOM_TOKENS


def test_high_user_override_does_not_inflate_history_compaction_reserve() -> None:
    config = _config(max_tokens=64_000, model_max_output_tokens=128_000)

    assert compaction_headroom_tokens(config) == CONTEXT_COMPACTION_HEADROOM_TOKENS


def test_stale_user_override_is_clamped_to_current_model_capability() -> None:
    config = _config(max_tokens=8_192, model_max_output_tokens=4_096)
    prompt = LlmPrompt(messages=[{"role": "user", "content": "Review."}])

    request_config = resolve_request_output_budget(config, prompt)

    assert request_config.max_tokens == 8_192
    assert request_config.model_max_output_tokens == 4_096
    assert request_config.request_max_output_tokens == 4_096


def test_all_provider_families_project_the_resolved_request_limit() -> None:
    prompt = LlmPrompt(messages=[{"role": "user", "content": "Review."}])
    resolved = resolve_request_output_budget(_config(max_tokens=64_000), prompt)

    chat = chat_completion_params(resolved, prompt, stream=False)
    responses = openai_responses.responses_params(resolved, prompt)
    anthropic = anthropic_messages._payload(
        resolved,
        prompt.messages,
    )
    gemini = google_gemini.gemini_payload(
        resolved,
        prompt.messages,
        [
            {
                "type": "function",
                "function": {
                    "name": "resume_lookup",
                    "parameters": {"type": "object"},
                },
            },
        ],
    )

    assert chat["max_tokens"] == 64_000
    assert responses["max_output_tokens"] == 64_000
    assert anthropic["max_tokens"] == 64_000
    assert gemini["generation_config"] == {"max_output_tokens": 64_000}
    assert gemini["tools"]


def test_dispatch_revalidates_input_after_each_tool_iteration(monkeypatch) -> None:
    captured_limits: list[int | None] = []

    async def fake_complete_tool_call(
        config: AgentLlmConfig,
        _prompt: LlmPrompt,
        _tools: list[dict[str, object]],
        **_kwargs: object,
    ) -> LlmAssistantMessage:
        captured_limits.append(config.request_max_output_tokens)
        return LlmAssistantMessage(content="Done", stop_reason="stop")

    monkeypatch.setattr(
        openai_chat,
        "complete_tool_call",
        fake_complete_tool_call,
    )
    config = _config(
        provider="ollama",
        provider_kind="local",
        api_family="openai_compatible_chat",
        context_window_tokens=20_000,
        model_max_output_tokens=None,
        max_tokens=16_000,
        supports_streaming=False,
    )
    prompt = LlmPrompt(messages=[{"role": "user", "content": "x" * 12_000}])
    tools: list[dict[str, object]] = [
        {
            "name": "resume_lookup",
            "parameters": {"type": "object", "properties": {}},
        },
    ]

    asyncio.run(_collect_events(async_stream_tool_call(config, prompt, tools)))
    prompt.messages.append({"role": "assistant", "content": "y" * 8_000})
    asyncio.run(_collect_events(async_stream_tool_call(config, prompt, tools)))

    assert captured_limits[0] is not None
    assert captured_limits[1] is not None
    assert captured_limits[1] < captured_limits[0]


@pytest.mark.parametrize(
    ("api_family", "adapter"),
    [
        ("openai_compatible_chat", openai_chat),
        ("openai_responses", openai_responses),
        ("anthropic_messages", anthropic_messages),
        ("google_gemini", google_gemini),
    ],
)
def test_dispatch_resolves_unary_stream_and_tool_budgets_at_one_seam(
    monkeypatch: pytest.MonkeyPatch,
    api_family: str,
    adapter: ModuleType,
) -> None:
    captured_limits: list[int | None] = []

    async def fake_complete(
        config: AgentLlmConfig,
        *_args: object,
        **_kwargs: object,
    ) -> LlmAssistantMessage:
        captured_limits.append(config.request_max_output_tokens)
        return LlmAssistantMessage(content="Done", stop_reason="stop")

    async def fake_stream(
        config: AgentLlmConfig,
        *_args: object,
        **_kwargs: object,
    ) -> AsyncIterator[LlmStreamEvent]:
        captured_limits.append(config.request_max_output_tokens)
        yield LlmStreamEvent(
            type="done",
            message=LlmAssistantMessage(content="Done", stop_reason="stop"),
        )

    monkeypatch.setattr(adapter, "complete", fake_complete)
    monkeypatch.setattr(adapter, "stream", fake_stream)
    monkeypatch.setattr(adapter, "complete_tool_call", fake_complete)
    config = _config(api_family=api_family, supports_streaming=False)
    prompt = LlmPrompt(messages=[{"role": "user", "content": "Review."}])
    tools: list[dict[str, object]] = [
        {
            "type": "function",
            "function": {
                "name": "resume_lookup",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    async def exercise() -> None:
        await async_complete_chat(config, prompt)
        assert [event.type async for event in async_stream_chat(config, prompt)] == [
            "done",
        ]
        await _collect_events(async_stream_tool_call(config, prompt, tools))

    asyncio.run(exercise())

    expected = 16_000 if api_family == "anthropic_messages" else None
    assert captured_limits == [expected, expected, expected]
