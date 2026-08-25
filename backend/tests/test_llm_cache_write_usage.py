from types import SimpleNamespace

import pytest

from app.services.llm.common import (
    anthropic_usage,
    openai_chat_usage,
    responses_usage,
    usage_from_values,
)


def test_openai_chat_usage_normalizes_cache_write_tokens_from_dict() -> None:
    usage = openai_chat_usage(
        {
            "usage": {
                "prompt_tokens": 2_006,
                "completion_tokens": 300,
                "total_tokens": 2_306,
                "prompt_tokens_details": {
                    "cached_tokens": 1_920,
                    "cache_write_tokens": 64,
                },
            }
        }
    )

    assert usage is not None
    assert usage.cached_input_tokens == 1_920
    assert usage.cache_write_input_tokens == 64


def test_openai_chat_usage_normalizes_cache_write_tokens_from_sdk_object() -> None:
    usage = openai_chat_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=2_006,
                completion_tokens=300,
                total_tokens=2_306,
                prompt_tokens_details=SimpleNamespace(
                    cached_tokens=1_920,
                    cache_write_tokens=64,
                ),
                completion_tokens_details=None,
            )
        )
    )

    assert usage is not None
    assert usage.cache_write_input_tokens == 64


def test_qwen_chat_usage_normalizes_explicit_cache_creation_tokens() -> None:
    usage = openai_chat_usage(
        {
            "usage": {
                "prompt_tokens": 2_006,
                "completion_tokens": 300,
                "total_tokens": 2_306,
                "prompt_tokens_details": {
                    "cached_tokens": 1_920,
                    "cache_creation_input_tokens": 64,
                },
            },
        },
    )

    assert usage is not None
    assert usage.cached_input_tokens == 1_920
    assert usage.cache_write_input_tokens == 64


def test_openai_chat_usage_normalizes_created_cache_tokens() -> None:
    usage = openai_chat_usage(
        {
            "usage": {
                "prompt_tokens": 2_006,
                "completion_tokens": 300,
                "total_tokens": 2_306,
                "prompt_tokens_details": {
                    "cached_tokens": 1_920,
                    "created_cache_tokens": 64,
                },
            },
        },
    )

    assert usage is not None
    assert usage.cached_input_tokens == 1_920
    assert usage.cache_write_input_tokens == 64


@pytest.mark.parametrize(
    ("preferred_field", "preferred_value"),
    [
        ("cache_write_tokens", 32),
        ("cache_creation_input_tokens", 48),
    ],
)
def test_created_cache_tokens_is_only_a_cache_write_fallback(
    preferred_field: str,
    preferred_value: int,
) -> None:
    usage = openai_chat_usage(
        {
            "usage": {
                "prompt_tokens_details": {
                    preferred_field: preferred_value,
                    "created_cache_tokens": 64,
                },
            },
        },
    )

    assert usage is not None
    assert usage.cache_write_input_tokens == preferred_value


def test_responses_usage_normalizes_cache_write_tokens_from_dict() -> None:
    usage = responses_usage(
        {
            "usage": {
                "input_tokens": 2_006,
                "output_tokens": 300,
                "total_tokens": 2_306,
                "input_tokens_details": {
                    "cached_tokens": 1_920,
                    "cache_write_tokens": 64,
                },
            }
        }
    )

    assert usage is not None
    assert usage.cached_input_tokens == 1_920
    assert usage.cache_write_input_tokens == 64


def test_responses_usage_normalizes_cache_write_tokens_from_sdk_object() -> None:
    usage = responses_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=2_006,
                output_tokens=300,
                total_tokens=2_306,
                input_tokens_details=SimpleNamespace(
                    cached_tokens=1_920,
                    cache_write_tokens=64,
                ),
                output_tokens_details=None,
            )
        )
    )

    assert usage is not None
    assert usage.cache_write_input_tokens == 64


def test_anthropic_usage_normalizes_cache_creation_as_cache_write() -> None:
    usage = anthropic_usage(
        {
            "usage": {
                "input_tokens": 8,
                "cache_creation_input_tokens": 5_120,
                "cache_read_input_tokens": 0,
                "output_tokens": 300,
            }
        }
    )

    assert usage is not None
    assert usage.input_tokens == 5_128
    assert usage.cache_write_input_tokens == 5_120


def test_cache_write_usage_alone_is_not_treated_as_empty() -> None:
    usage = usage_from_values(cache_write_input_tokens="64")

    assert usage is not None
    assert usage.cache_write_input_tokens == 64


def test_invalid_cache_write_usage_does_not_create_usage() -> None:
    assert usage_from_values(cache_write_input_tokens=-1) is None
