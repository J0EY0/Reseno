from typing import get_args, get_type_hints

import pytest

from app.services.llm import common, dispatch
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
    openai_chat,
    openai_responses,
)
from app.services.llm.types import (
    LlmAssistantInputMessage,
    LlmContentPart,
    LlmFilePart,
    LlmImagePart,
    LlmInputMessage,
    LlmSystemMessage,
    LlmTextPart,
    LlmToolMessage,
    LlmUserMessage,
)


def test_public_llm_input_seam_is_role_and_content_typed() -> None:
    assert (
        get_type_hints(dispatch.async_complete_chat)["messages"]
        == list[LlmInputMessage]
    )
    assert set(get_args(LlmInputMessage)) == {
        LlmSystemMessage,
        LlmUserMessage,
        LlmAssistantInputMessage,
        LlmToolMessage,
    }
    assert set(get_args(LlmContentPart)) == {
        LlmTextPart,
        LlmImagePart,
        LlmFilePart,
    }

    # Cache placement is provider wire behavior, not part of the transcript.
    for content_part in get_args(LlmContentPart):
        assert "cache_control" not in content_part.__annotations__
        assert "prompt_cache_key" not in content_part.__annotations__


@pytest.mark.parametrize(
    "entry_point",
    [
        dispatch.async_complete_tool_call,
        dispatch.async_stream_chat,
        common.chat_completion_params,
        common.openai_chat_messages,
        common.system_and_messages,
        openai_chat.complete,
        openai_chat.complete_tool_call,
        openai_chat.stream,
        openai_chat.stream_tool_call,
        openai_responses.complete,
        openai_responses.complete_tool_call,
        openai_responses.stream,
        openai_responses.stream_tool_call,
        openai_responses.responses_params,
        openai_responses.responses_input,
        anthropic_messages.complete,
        anthropic_messages.complete_tool_call,
        anthropic_messages.stream,
        anthropic_messages.stream_tool_call,
        anthropic_messages.anthropic_messages,
        google_gemini.complete,
        google_gemini.complete_tool_call,
        google_gemini.stream,
        google_gemini.stream_tool_call,
        google_gemini.gemini_payload,
        google_gemini.gemini_input,
    ],
)
def test_every_provider_entry_point_shares_the_typed_message_seam(
    entry_point: object,
) -> None:
    assert get_type_hints(entry_point)["messages"] == list[LlmInputMessage]
