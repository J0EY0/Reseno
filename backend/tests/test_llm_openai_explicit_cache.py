from copy import deepcopy

import pytest

from app.services.llm.adapters import openai_responses
from app.services.llm.errors import LlmRequestError
from app.services.llm.types import AgentLlmConfig, LlmPrompt, LlmRequestContext


def _config(**overrides: object) -> AgentLlmConfig:
    values: dict[str, object] = {
        "client_id": "openai-explicit-cache-test",
        "name": "OpenAI GPT-5.6",
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "temperature": None,
        "top_p": None,
        "max_tokens": None,
        "timeout_seconds": 30,
        "provider_kind": "cloud",
        "api_family": "openai_responses",
    }
    values.update(overrides)
    return AgentLlmConfig(**values)  # type: ignore[arg-type]


def test_gpt_5_6_projects_declared_message_prefixes_to_responses_breakpoints() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "system", "content": "Stable policy"},
            {"role": "user", "content": "Historical question"},
            {"role": "assistant", "content": "Historical answer"},
            {"role": "user", "content": "Current workspace"},
            {"role": "user", "content": "Current request"},
        ],
        stable_prefix_message_counts=(2, 3, 4, 5),
    )
    original_messages = deepcopy(prompt.messages)

    params = openai_responses.responses_params(
        _config(),
        prompt,
        request_context=LlmRequestContext(cache_key="resume-session-1"),
    )

    assert params["prompt_cache_key"] == "resume-session-1"
    assert params["extra_body"] == {
        "prompt_cache_options": {"mode": "explicit"},
    }
    assert params["instructions"] == "Stable policy"
    assert [
        item["content"][-1]["prompt_cache_breakpoint"] for item in params["input"]
    ] == [{"mode": "explicit"}] * 4
    assert prompt.messages == original_messages


def test_tool_loop_appends_do_not_move_existing_message_prefixes() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "system", "content": "Stable policy"},
            {"role": "user", "content": "Stable current request"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "done"},
        ],
        stable_prefix_message_counts=(2,),
    )

    params = openai_responses.responses_params(
        _config(),
        prompt,
        request_context=LlmRequestContext(cache_key="resume-session-1"),
    )

    stable_user = params["input"][0]
    assert stable_user["content"][-1]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
    }
    assert params["input"][1]["type"] == "function_call"
    assert params["input"][2]["type"] == "function_call_output"


def test_multimodal_prefix_marks_the_last_responses_content_block() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "system", "content": "Stable policy"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Review this file"},
                    {
                        "type": "file",
                        "filename": "resume.pdf",
                        "media_type": "application/pdf",
                        "data": "cGRm",
                    },
                ],
            },
        ],
        stable_prefix_message_counts=(2,),
    )
    original_messages = deepcopy(prompt.messages)

    params = openai_responses.responses_params(
        _config(),
        prompt,
        request_context=LlmRequestContext(cache_key="resume-session-1"),
    )

    content = params["input"][0]["content"]
    assert "prompt_cache_breakpoint" not in content[0]
    assert content[1]["type"] == "input_file"
    assert content[1]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert prompt.messages == original_messages


def test_explicit_cache_projects_only_the_latest_fifty_declared_prefixes() -> None:
    prompt = LlmPrompt(
        messages=[{"role": "user", "content": f"turn-{index}"} for index in range(52)],
        stable_prefix_message_counts=tuple(range(1, 53)),
    )

    params = openai_responses.responses_params(
        _config(),
        prompt,
        request_context=LlmRequestContext(cache_key="resume-session-1"),
    )

    assert params["input"][0]["content"] == "turn-0"
    assert params["input"][1]["content"] == "turn-1"
    assert all(
        item["content"][-1]["prompt_cache_breakpoint"] == {"mode": "explicit"}
        for item in params["input"][2:]
    )


def test_declared_prefix_that_has_no_cacheable_content_fails_closed() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "system", "content": "Stable policy"},
            {"role": "user", "content": "Current request"},
        ],
        stable_prefix_message_counts=(1,),
    )

    with pytest.raises(LlmRequestError, match="cannot be mapped"):
        openai_responses.responses_params(
            _config(),
            prompt,
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        )


def test_tool_only_assistant_prefix_fails_closed() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "user", "content": "Use a tool"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": "{}"},
                    },
                ],
            },
        ],
        stable_prefix_message_counts=(2,),
    )

    with pytest.raises(LlmRequestError, match="cannot be mapped"):
        openai_responses.responses_params(_config(), prompt)


def test_prefix_ending_on_a_hoisted_system_message_fails_closed() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "user", "content": "Prior turn"},
            {"role": "system", "content": "Later policy"},
        ],
        stable_prefix_message_counts=(2,),
    )

    with pytest.raises(LlmRequestError, match="cannot be mapped"):
        openai_responses.responses_params(_config(), prompt)


def test_system_message_after_a_declared_prefix_fails_closed() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "system", "content": "Initial policy"},
            {"role": "user", "content": "Apparently stable"},
            {"role": "system", "content": "Later changing policy"},
            {"role": "user", "content": "Current request"},
        ],
        stable_prefix_message_counts=(2,),
    )

    with pytest.raises(LlmRequestError, match="cannot be mapped"):
        openai_responses.responses_params(
            _config(),
            prompt,
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        )


def test_system_message_between_declared_prefixes_fails_closed() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "user", "content": "First stable turn"},
            {"role": "system", "content": "Later policy"},
            {"role": "user", "content": "Second stable turn"},
        ],
        stable_prefix_message_counts=(1, 3),
    )

    with pytest.raises(LlmRequestError, match="cannot be mapped"):
        openai_responses.responses_params(
            _config(),
            prompt,
            request_context=LlmRequestContext(cache_key="resume-session-1"),
        )


def test_gpt_5_6_without_declared_prefixes_keeps_implicit_cache_mode() -> None:
    params = openai_responses.responses_params(
        _config(),
        LlmPrompt(messages=[{"role": "user", "content": "Current request"}]),
        request_context=LlmRequestContext(cache_key="resume-session-1"),
    )

    assert params["prompt_cache_key"] == "resume-session-1"
    assert "extra_body" not in params
    assert params["input"] == [{"role": "user", "content": "Current request"}]


def test_declared_prefix_enables_explicit_mode_without_a_cache_routing_key() -> None:
    params = openai_responses.responses_params(
        _config(),
        LlmPrompt(
            messages=[{"role": "user", "content": "Stable request"}],
            stable_prefix_message_counts=(1,),
        ),
    )

    assert "prompt_cache_key" not in params
    assert params["extra_body"] == {
        "prompt_cache_options": {"mode": "explicit"},
    }
    assert params["input"][0]["content"][-1]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "gpt-5.5"},
        {
            "provider": "xai",
            "model": "grok-4.5",
            "base_url": "https://api.x.ai/v1",
        },
        {
            "provider_kind": "custom",
            "base_url": "https://proxy.example.test/v1",
        },
        {"base_url": "https://proxy.example.test/v1"},
    ],
)
def test_non_official_or_unsupported_responses_targets_get_no_explicit_fields(
    overrides: dict[str, object],
) -> None:
    params = openai_responses.responses_params(
        _config(**overrides),
        LlmPrompt(
            messages=[{"role": "user", "content": "Stable request"}],
            stable_prefix_message_counts=(1,),
        ),
        request_context=LlmRequestContext(cache_key="resume-session-1"),
    )

    assert "extra_body" not in params
    assert params["input"] == [{"role": "user", "content": "Stable request"}]
