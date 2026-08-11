import json
from functools import partial

import anyio
import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationCheckpoint,
)
from app.services.agent.runtime import compaction
from app.services.agent.runtime.compaction import prepare_agent_messages
from app.services.agent.runtime.context import AgentRunAborted, AgentRuntimeContext
from app.services.agent.runtime.messages import (
    agent_compaction_events,
    estimate_agent_messages_tokens,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestError,
    LlmTimeoutError,
)
from app.services.llm.types import LlmContentPart, LlmInputMessage


def _config(*, context_window_tokens: int = 4_000) -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="compaction-model",
        name="Compaction model",
        provider="openai",
        provider_kind="cloud",
        api_family="openai_responses",
        model="gpt-test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        temperature=0.2,
        top_p=0.9,
        max_tokens=512,
        timeout_seconds=30,
        context_window_tokens=context_window_tokens,
        supports_streaming=False,
    )


def _request(
    history: list[dict[str, object]],
    *,
    prompt: str = "Use option two and keep British English.",
    current_id: str = "current-user",
) -> AgentChatRequest:
    return AgentChatRequest(
        message={
            "id": current_id,
            "role": "user",
            "text": prompt,
        },
        messages=history,
        locale="en",
        resume={"basic": {"name": "Private Person"}, "sections": []},
    )


def _long_history() -> list[dict[str, object]]:
    history: list[dict[str, object]] = [
        {
            "id": "goal-user",
            "role": "user",
            "text": "Give me two ways to shorten the project section.",
        },
        {
            "id": "options-assistant",
            "role": "assistant",
            "text": (
                "Option one removes the Redis detail. Option two keeps the "
                "Redis migration bullet."
            ),
        },
        {
            "id": "style-user",
            "role": "user",
            "text": "Write every answer in British English.",
        },
        {
            "id": "style-assistant",
            "role": "assistant",
            "text": "Understood.",
        },
    ]
    for index in range(8):
        history.extend(
            [
                {
                    "id": f"filler-user-{index}",
                    "role": "user",
                    "text": f"Continue review {index}. " + ("context " * 35),
                },
                {
                    "id": f"filler-assistant-{index}",
                    "role": "assistant",
                    "text": f"Review result {index}. " + ("analysis " * 35),
                },
            ],
        )
    return history


def test_compaction_sanitizes_model_visible_message_ids() -> None:
    request = _request(
        [
            {
                "id": "Private_Person-history",
                "role": "user",
                "text": "Review this section.",
            },
        ],
    )

    events = agent_compaction_events(request, start_count=0, end_count=1)

    assert events == [
        {
            "id": "[redacted_name]-history",
            "role": "user",
            "text": "Review this section.",
        },
    ]


def test_compaction_summarizes_ordered_prefix_and_keeps_native_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[dict[str, object]]] = []

    async def fake_complete(
        _config: AgentLlmConfig,
        messages: list[dict[str, object]],
        **_kwargs: object,
    ) -> LlmAssistantMessage:
        captured.append(messages)
        return LlmAssistantMessage(
            content=(
                "Goal: shorten the project section.\n"
                "Constraints: use British English.\n"
                "Decisions: option two keeps the Redis migration bullet."
            ),
            stop_reason="stop",
        )

    monkeypatch.setattr(compaction, "async_complete_chat", fake_complete)
    request = _request(_long_history())

    messages = anyio.run(
        partial(
            prepare_agent_messages,
            request,
            _config(),
            AgentRuntimeContext(),
            mode="streaming_final",
        ),
    )

    assert captured
    compiler_input = json.loads(captured[0][1]["content"])[
        "conversationCompactionInput"
    ]
    ordered_text = [event.get("text") for event in compiler_input["conversation"]]
    assert ordered_text.index("Give me two ways to shorten the project section.") < (
        ordered_text.index(
            "Option one removes the Redis detail. Option two keeps the Redis "
            "migration bullet.",
        )
    )
    assert request._active_conversation_checkpoint is not None
    assert request._active_conversation_checkpoint.summary.startswith("Goal:")
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "conversationSummary" in serialized
    assert "option two keeps the Redis migration bullet" in serialized
    assert request.message.text in serialized
    assert "Private Person" not in serialized


def test_loaded_checkpoint_is_reused_without_calling_summarizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_complete(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("summarizer must not run below the refresh trigger")

    monkeypatch.setattr(compaction, "async_complete_chat", unexpected_complete)
    history = [
        {"id": "old-user", "role": "user", "text": "Review my resume."},
        {"id": "old-assistant", "role": "assistant", "text": "Reviewed."},
        {"id": "tail-user", "role": "user", "text": "Keep the project."},
        {"id": "tail-assistant", "role": "assistant", "text": "Kept."},
    ]
    request = _request(history, prompt="Continue.")
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="old-assistant",
        summary="Goal: review the resume.",
    )
    request._loaded_conversation_checkpoint = checkpoint
    request._active_conversation_checkpoint = checkpoint

    messages = anyio.run(
        partial(
            prepare_agent_messages,
            request,
            _config(context_window_tokens=16_000),
            AgentRuntimeContext(),
            mode="streaming_final",
        ),
    )

    assert request._active_conversation_checkpoint == checkpoint
    assert "Review my resume." not in json.dumps(messages)
    assert "Keep the project." in json.dumps(messages)


def test_truncated_compaction_does_not_advance_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def truncated_complete(
        *_args: object,
        **_kwargs: object,
    ) -> LlmAssistantMessage:
        return LlmAssistantMessage(content="partial", stop_reason="length")

    monkeypatch.setattr(compaction, "async_complete_chat", truncated_complete)
    request = _request(_long_history())
    loaded = AgentConversationCheckpoint(
        throughMessageId="style-assistant",
        summary="Goal: shorten the project section.",
    )
    request._loaded_conversation_checkpoint = loaded
    request._active_conversation_checkpoint = loaded

    with pytest.raises(LlmRequestError, match="truncated"):
        anyio.run(
            partial(
                prepare_agent_messages,
                request,
                _config(),
                AgentRuntimeContext(),
                mode="streaming_final",
            ),
        )

    assert request._active_conversation_checkpoint == loaded


def test_compaction_resanitizes_a_loaded_summary_for_current_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_inputs: list[dict[str, object]] = []

    async def fake_complete(
        _config: AgentLlmConfig,
        messages: list[dict[str, object]],
        **_kwargs: object,
    ) -> LlmAssistantMessage:
        captured_inputs.append(json.loads(str(messages[1]["content"])))
        return LlmAssistantMessage(
            content="Goal: keep the resume concise.",
            stop_reason="stop",
        )

    monkeypatch.setattr(compaction, "async_complete_chat", fake_complete)
    request = _request(_long_history())
    request.resume["basic"]["name"] = "Bob Smith"
    loaded = AgentConversationCheckpoint(
        throughMessageId="style-assistant",
        summary="Earlier candidate: BOB_SMITH.",
    )
    request._loaded_conversation_checkpoint = loaded
    request._active_conversation_checkpoint = loaded

    anyio.run(
        partial(
            prepare_agent_messages,
            request,
            _config(),
            AgentRuntimeContext(),
            mode="streaming_final",
        ),
    )

    compiler_input = captured_inputs[0]["conversationCompactionInput"]
    assert isinstance(compiler_input, dict)
    assert compiler_input["previousSummary"] == "Earlier candidate: [redacted_name]."
    assert "BOB_SMITH" not in json.dumps(captured_inputs)


def test_compaction_cancellation_does_not_commit_a_candidate_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aborted = False

    async def fake_complete(
        *_args: object,
        **_kwargs: object,
    ) -> LlmAssistantMessage:
        nonlocal aborted
        aborted = True
        return LlmAssistantMessage(
            content="Goal: keep the resume concise.",
            stop_reason="stop",
        )

    async def is_aborted() -> bool:
        return aborted

    monkeypatch.setattr(compaction, "async_complete_chat", fake_complete)
    request = _request(_long_history())
    loaded = AgentConversationCheckpoint(
        throughMessageId="style-assistant",
        summary="Goal: preserve the current draft.",
    )
    request._loaded_conversation_checkpoint = loaded
    request._active_conversation_checkpoint = loaded

    with pytest.raises(AgentRunAborted):
        anyio.run(
            partial(
                prepare_agent_messages,
                request,
                _config(),
                AgentRuntimeContext(is_aborted=is_aborted),
                mode="streaming_final",
            ),
        )

    assert request._active_conversation_checkpoint == loaded


def test_compaction_retries_timeout_once_without_advancing_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls = 0

    async def timed_out(*_args: object, **_kwargs: object) -> LlmAssistantMessage:
        nonlocal provider_calls
        provider_calls += 1
        raise LlmTimeoutError("idle timeout")

    monkeypatch.setattr(compaction, "async_complete_chat", timed_out)
    request = _request(_long_history())
    loaded = AgentConversationCheckpoint(
        throughMessageId="style-assistant",
        summary="Goal: preserve the current draft.",
    )
    request._loaded_conversation_checkpoint = loaded
    request._active_conversation_checkpoint = loaded

    with pytest.raises(LlmTimeoutError):
        anyio.run(
            partial(
                prepare_agent_messages,
                request,
                _config(),
                AgentRuntimeContext(),
                mode="streaming_final",
            ),
        )

    assert provider_calls == 2
    assert request._active_conversation_checkpoint == loaded


def test_later_compaction_failure_does_not_commit_an_earlier_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls = 0

    def select_one_segment(
        *_args: object,
        boundaries: list[tuple[int, str]],
        **_kwargs: object,
    ) -> tuple[int, str]:
        return boundaries[0]

    async def fail_second_segment(
        *_args: object,
        **_kwargs: object,
    ) -> LlmAssistantMessage:
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            return LlmAssistantMessage(
                content="Oversized summary " * 400,
                stop_reason="stop",
            )
        raise LlmRequestError("second compaction segment failed")

    monkeypatch.setattr(compaction, "async_complete_chat", fail_second_segment)
    monkeypatch.setattr(compaction, "_select_boundary", select_one_segment)
    request = _request(_long_history())
    loaded = AgentConversationCheckpoint(
        throughMessageId="style-assistant",
        summary="Goal: preserve the current draft.",
    )
    request._loaded_conversation_checkpoint = loaded
    request._active_conversation_checkpoint = loaded

    with pytest.raises(LlmRequestError, match="second compaction segment failed"):
        anyio.run(
            partial(
                prepare_agent_messages,
                request,
                _config(),
                AgentRuntimeContext(),
                mode="streaming_final",
            ),
        )

    assert provider_calls == 2
    assert request._active_conversation_checkpoint == loaded


def test_compaction_never_discards_the_only_recent_user_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_complete(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("there is no complete older turn to summarize")

    monkeypatch.setattr(compaction, "async_complete_chat", unexpected_complete)
    request = _request(
        [
            {
                "id": "only-user",
                "role": "user",
                "text": "Keep this exact turn. " + ("large " * 1_500),
            },
        ],
        prompt="Continue.",
    )

    with pytest.raises(LlmRequestError, match="context window"):
        anyio.run(
            partial(
                prepare_agent_messages,
                request,
                _config(context_window_tokens=2_000),
                AgentRuntimeContext(),
                mode="streaming_final",
            ),
        )


@pytest.mark.parametrize("mode", ["tools", "streaming_final"])
def test_workspace_snapshot_keeps_edit_turn_prompt_as_next_turn_prefix(
    mode: str,
) -> None:
    config = _config(context_window_tokens=16_000)
    first = _request([], prompt="Create a concise draft.")
    first.resume["basic"]["headline"] = "Frontend Engineer"
    first_messages = anyio.run(
        partial(
            prepare_agent_messages,
            first,
            config,
            AgentRuntimeContext(),
            mode=mode,
        ),
    )
    snapshot = first._active_workspace_snapshots
    assert snapshot is not None

    second = _request(
        [
            first.message.model_dump(mode="json"),
            {
                "id": "first-assistant",
                "role": "assistant",
                "text": "The draft is ready.",
            },
        ],
        prompt="Shorten the second bullet.",
        current_id="second-user",
    )
    # The authoritative workspace changed after the first edit. Replaying the
    # immutable compiler event before its historical user turn preserves the
    # previous provider messages while the current snapshot reflects new state.
    second.resume["basic"]["headline"] = "AI Frontend Engineer"
    second._historical_workspace_snapshots = {
        first.message.id: snapshot,
    }
    second_messages = anyio.run(
        partial(
            prepare_agent_messages,
            second,
            config,
            AgentRuntimeContext(),
            mode=mode,
        ),
    )

    assert second_messages[: len(first_messages)] == first_messages
    assert "AI Frontend Engineer" in str(second_messages[-2]["content"])


def test_native_image_token_estimate_is_independent_of_base64_size() -> None:
    def estimate(data: str) -> int:
        return estimate_agent_messages_tokens(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image."},
                        {
                            "type": "image",
                            "media_type": "image/png",
                            "data": data,
                        },
                    ],
                },
            ],
        )

    assert estimate("YQ==") == estimate("A" * 1_000_000)
    assert estimate("YQ==") < 10_000


def test_native_file_token_estimate_is_independent_of_base64_size() -> None:
    def estimate(data: str) -> int:
        return estimate_agent_messages_tokens(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Review this document."},
                        {
                            "type": "file",
                            "filename": "resume.pdf",
                            "media_type": "application/pdf",
                            "data": data,
                        },
                    ],
                },
            ],
        )

    assert estimate("YQ==") == estimate("A" * 1_000_000)
    assert 30_000 < estimate("YQ==") < 40_000


def test_native_media_token_reserves_accumulate_per_attachment() -> None:
    text_part: LlmContentPart = {
        "type": "text",
        "text": "Compare these materials.",
    }
    image_part: LlmContentPart = {
        "type": "image",
        "media_type": "image/png",
        "data": "A" * 1_000_000,
    }
    file_part: LlmContentPart = {
        "type": "file",
        "filename": "resume.pdf",
        "media_type": "application/pdf",
        "data": "A" * 1_000_000,
    }

    def estimate(parts: list[LlmContentPart]) -> int:
        messages: list[LlmInputMessage] = [{"role": "user", "content": parts}]
        return estimate_agent_messages_tokens(messages)

    text_only = estimate([text_part])
    one_image = estimate([text_part, image_part])
    two_images = estimate([text_part, image_part, image_part])
    images_and_file = estimate([text_part, image_part, image_part, file_part])

    assert 4_000 < one_image - text_only < 4_200
    assert 4_000 < two_images - one_image < 4_200
    assert 32_000 < images_and_file - two_images < 32_200


def test_plain_text_token_estimate_is_unchanged() -> None:
    assert (
        estimate_agent_messages_tokens(
            [{"role": "user", "content": "ordinary text"}],
        )
        == 11
    )
