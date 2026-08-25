from copy import deepcopy
from typing import Any

import pytest

from app.services.llm.common import chat_completion_params, openai_chat_usage
from app.services.llm.types import AgentLlmConfig, LlmPrompt


def _config(**overrides: Any) -> AgentLlmConfig:
    values: dict[str, Any] = {
        "client_id": "qwen-cache-test",
        "name": "Qwen cache test",
        "provider": "qwen",
        "model": "qwen3.7-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "secret",
        "temperature": 0,
        "top_p": 1,
        "max_tokens": None,
        "timeout_seconds": 60,
        "provider_kind": "cloud",
        "api_family": "openai_compatible_chat",
    }
    values.update(overrides)
    return AgentLlmConfig(**values)


def test_official_qwen_projects_only_the_latest_four_stable_prefixes() -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "system", "content": "stable policy"},
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "answer 1"},
            {"role": "user", "content": "turn 2"},
            {"role": "assistant", "content": "answer 2"},
            {"role": "user", "content": "current request"},
        ],
        stable_prefix_message_counts=(2, 3, 4, 5, 6),
    )
    original_messages = deepcopy(prompt.messages)

    params = chat_completion_params(_config(), prompt, stream=False)

    assert params["messages"][1]["content"] == "turn 1"
    assert [
        message["content"][-1]["cache_control"] for message in params["messages"][2:]
    ] == [{"type": "ephemeral"}] * 4
    assert prompt.messages == original_messages


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "custom"},
        {"provider_kind": "custom"},
        {"api_family": "openai_responses"},
        {
            "base_url": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        },
        {"model": "qwen-max"},
    ],
)
def test_non_official_qwen_variant_does_not_emit_explicit_cache_fields(
    overrides: dict[str, Any],
) -> None:
    prompt = LlmPrompt(
        messages=[
            {"role": "user", "content": "stable history"},
            {"role": "user", "content": "current request"},
        ],
        stable_prefix_message_counts=(1, 2),
    )

    params = chat_completion_params(
        _config(**overrides),
        prompt,
        stream=False,
    )

    assert params["messages"] == prompt.messages


def test_qwen_cache_creation_usage_is_normalized_as_a_cache_write() -> None:
    usage = openai_chat_usage(
        {
            "usage": {
                "prompt_tokens": 2_048,
                "completion_tokens": 64,
                "total_tokens": 2_112,
                "prompt_tokens_details": {
                    "cached_tokens": 1_024,
                    "cache_creation_input_tokens": 1_024,
                },
            },
        },
    )

    assert usage is not None
    assert usage.cached_input_tokens == 1_024
    assert usage.cache_write_input_tokens == 1_024


def test_qwen_places_cache_control_on_the_tail_of_multimodal_content() -> None:
    prompt = LlmPrompt(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect this"},
                    {
                        "type": "image",
                        "media_type": "image/png",
                        "data": "YWJj",
                    },
                ],
            },
        ],
        stable_prefix_message_counts=(1,),
    )

    content = chat_completion_params(
        _config(model="qwen3-vl-plus"),
        prompt,
        stream=False,
    )["messages"][0]["content"]

    assert "cache_control" not in content[0]
    assert content[-1]["cache_control"] == {"type": "ephemeral"}
