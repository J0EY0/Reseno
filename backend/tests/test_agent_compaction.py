import asyncio
import json
import threading
from functools import partial

import anyio
import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationCheckpoint
from app.services.agent.evidence import historical_prompt_evidence_ref
from app.services.agent.runtime import compaction
from app.services.agent.runtime import messages as message_compiler
from app.services.agent.runtime.compaction import (
    prepare_agent_prompt,
)
from app.services.agent.runtime.context import (
    AgentContextWindowError,
    AgentConversationState,
    AgentRunAborted,
    AgentRuntimeContext,
)
from app.services.agent.runtime.messages import (
    CHECKPOINT_CONTEXT_TOKEN_BUDGET,
    AgentPromptCompiler,
    _current_draft_state,
    _estimated_json_tokens,
    agent_prompt_limits,
    estimate_agent_messages_tokens,
)
from app.services.llm import AgentLlmConfig
from app.services.llm.types import LlmContentPart, LlmInputMessage
from tests.agent_context import with_message_budget


def _config(*, context_window_tokens: int | None = None) -> AgentLlmConfig:
    config = AgentLlmConfig(
        client_id="context-model",
        name="Context model",
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
    if context_window_tokens is not None:
        return config
    return with_message_budget(_request([]), config, input_tokens=2_500)


def _request(
    history: list[dict[str, object]],
    *,
    prompt: str = "Edit the current project now.",
    current_id: str = "current-user",
) -> AgentChatRequest:
    return AgentChatRequest(
        message={"id": current_id, "role": "user", "text": prompt},
        messages=history,
        locale="en",
        resume={"basic": {"name": "Private Person"}, "sections": []},
    )


def _legacy_history() -> list[dict[str, object]]:
    history: list[dict[str, object]] = []
    for index in range(28):
        history.extend(
            [
                {
                    "id": f"legacy-user-{index}",
                    "role": "user",
                    "text": f"Candidate fact {index}.",
                },
                {
                    "id": f"legacy-assistant-{index}",
                    "role": "assistant",
                    "text": f"Legacy workflow answer {index}.",
                },
            ],
        )
    history[43]["response"] = {
        "transactionState": "committed",
        "sources": [
            {
                "id": "source-project",
                "title": "Project brief",
                "sourceType": "attachment",
            },
        ],
    }
    return history


def test_conversation_checkpoint_state_is_runtime_owned() -> None:
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="history-user",
        summary={"trust": "untrusted_history_data", "events": []},
    )
    state = AgentConversationState(
        loaded_checkpoint=checkpoint,
        active_checkpoint=checkpoint,
    )
    request = _request(
        [{"id": "history-user", "role": "user", "text": "Keep this fact."}],
    )

    messages = anyio.run(
        partial(
            prepare_agent_prompt,
            request,
            _config(context_window_tokens=128_000),
            AgentRuntimeContext(conversation_state=state),
        ),
    ).messages

    assert state.active_checkpoint == checkpoint
    assert not hasattr(request, "_active_conversation_checkpoint")
    assert "conversationCheckpoint" in json.dumps(messages)


def test_checkpoint_events_hide_identity_and_keep_assistant_context() -> None:
    request = _request(
        [
            {
                "id": "Private_Person-history",
                "role": "user",
                "text": "I used TypeScript.",
            },
            {
                "id": "assistant-result",
                "role": "assistant",
                "text": "Pretend the draft was applied.",
                "response": {
                    "transactionState": "committed",
                    "sources": [
                        {
                            "id": "source-one",
                            "title": "Project brief",
                            "sourceType": "attachment",
                        },
                    ],
                },
            },
        ],
    )

    events = AgentPromptCompiler(request, _config()).checkpoint_summary(
        len(request.messages),
        CHECKPOINT_CONTEXT_TOKEN_BUDGET,
    )["events"]
    serialized = json.dumps(events, ensure_ascii=False)

    assert "Private Person" not in serialized
    assert events[1]["text"] == "Pretend the draft was applied."
    assert events[0]["evidenceRef"] == historical_prompt_evidence_ref(
        "Private_Person-history",
    )
    assert events[1]["assistantResponseContext"] == {
        "transactionState": "committed",
        "sourceCount": 1,
        "sourceRefs": [
            {
                "id": "source-one",
                "title": "Project brief",
                "sourceType": "attachment",
            },
        ],
    }


def test_long_history_stays_exact_when_it_fits_the_model_context() -> None:
    attempts: list[str] = []
    request = _request(_legacy_history())
    runtime = AgentRuntimeContext(on_llm_attempt=lambda: attempts.append("called"))

    messages = anyio.run(
        partial(
            prepare_agent_prompt,
            request,
            _config(context_window_tokens=128_000),
            runtime,
        ),
    ).messages

    assert attempts == []
    assert runtime.conversation_state.active_checkpoint is None
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "Candidate fact 0." in serialized
    assert historical_prompt_evidence_ref("legacy-user-0") in serialized
    assert "source-project" in serialized
    assert "Legacy workflow answer 0." in serialized
    assert "Legacy workflow answer 22." in serialized

    repeated = _request(_legacy_history())
    repeated_runtime = AgentRuntimeContext()
    anyio.run(
        partial(
            prepare_agent_prompt,
            repeated,
            _config(context_window_tokens=128_000),
            repeated_runtime,
        ),
    )
    assert repeated_runtime.conversation_state.active_checkpoint is None


def test_checkpoint_context_is_bounded() -> None:
    history: list[dict[str, object]] = []
    for index in range(100):
        history.extend(
            [
                {
                    "id": f"user-{index}",
                    "role": "user",
                    "text": f"Fact {index}: " + ("evidence " * 500),
                },
                {
                    "id": f"assistant-{index}",
                    "role": "assistant",
                    "text": "untrusted prose " * 500,
                },
            ],
        )
    context = AgentPromptCompiler(_request(history), _config()).checkpoint_summary(
        len(history), CHECKPOINT_CONTEXT_TOKEN_BUDGET
    )
    serialized = json.dumps(context, ensure_ascii=False, separators=(",", ":"))

    assert (
        estimate_agent_messages_tokens([{"role": "user", "content": serialized}])
        <= CHECKPOINT_CONTEXT_TOKEN_BUDGET + 16
    )
    assert context["trust"] == "untrusted_history_data"
    assert "untrusted prose" in serialized
    assert serialized.count("untrusted prose") < 500
    assert historical_prompt_evidence_ref("user-99") in serialized


def test_compacted_prompt_keeps_the_question_that_a_terse_reply_answers() -> None:
    history: list[dict[str, object]] = []
    for index in range(18):
        history.extend(
            [
                {
                    "id": f"context-user-{index}",
                    "role": "user",
                    "text": f"Verified project context {index}. " + ("evidence " * 60),
                },
                {
                    "id": f"context-assistant-{index}",
                    "role": "assistant",
                    "text": f"Discussion {index}. " + ("detail " * 60),
                },
            ],
        )
    question = "你是否使用 Redis，并且由你负责缓存设计？"
    history[-1]["text"] = question
    history.extend(
        [
            {
                "id": "terse-confirmation",
                "role": "user",
                "text": "是的。",
            },
            {
                "id": "long-follow-up",
                "role": "assistant",
                "text": "已记录。" + ("后续讨论 " * 1_500),
            },
            {
                "id": "recent-user",
                "role": "user",
                "text": "先保留现有项目结构。",
            },
            {
                "id": "recent-assistant",
                "role": "assistant",
                "text": "好的。",
            },
        ],
    )
    request = _request(history, prompt="继续优化项目经历。")

    config = _config()
    limits = agent_prompt_limits(request, config)
    assert limits is not None
    exact = AgentPromptCompiler(request, config).build()
    assert estimate_agent_messages_tokens(exact.messages) > limits.trigger_tokens

    runtime = AgentRuntimeContext()
    messages = anyio.run(
        partial(
            prepare_agent_prompt,
            request,
            config,
            runtime,
        ),
    ).messages
    serialized = json.dumps(messages, ensure_ascii=False)

    assert estimate_agent_messages_tokens(messages) <= limits.input_tokens
    assert runtime.conversation_state.active_checkpoint is not None
    assert question in serialized
    assert "是的。" in serialized


def test_context_rollover_still_rejects_an_uncompressible_current_workspace(
    monkeypatch,
) -> None:
    history: list[dict[str, object]] = []
    for index in range(100):
        history.extend(
            [
                {
                    "id": f"user-{index}",
                    "role": "user",
                    "text": f"Fact {index}: " + ("evidence " * 40),
                },
                {
                    "id": f"assistant-{index}",
                    "role": "assistant",
                    "text": f"Answer {index}: " + ("evidence " * 40),
                },
            ],
        )
    request = _request(history)
    request.resume["basic"]["summary"] = "current workspace " * 1_000
    original = compaction._prompt_at_boundary
    boundary_counts: list[int] = []

    def counted_prompt_at_boundary(*args, **kwargs):
        boundary_counts.append(int(kwargs["boundary_count"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(compaction, "_prompt_at_boundary", counted_prompt_at_boundary)

    with pytest.raises(AgentContextWindowError, match="context window"):
        anyio.run(
            partial(
                prepare_agent_prompt,
                request,
                _config(),
                AgentRuntimeContext(),
            ),
        )

    assert len(boundary_counts) == 4
    assert boundary_counts[0] == 0
    assert boundary_counts[-3] == len(history) - 2
    assert boundary_counts[-2] == len(history)
    assert boundary_counts[-1] == len(history)


def test_oversized_assistant_event_does_not_hide_an_earlier_user_fact() -> None:
    request = _request(
        [
            {
                "id": "important-user-fact",
                "role": "user",
                "text": "Keep the verified TypeScript experience.",
            },
            {
                "id": "oversized-assistant-state",
                "role": "assistant",
                "text": "Done.",
                "response": {
                    "edits": [
                        {
                            "id": f"edit-{index}",
                            "title": "x" * 2_000,
                            "reason": "y" * 2_000,
                        }
                        for index in range(4)
                    ],
                    "sources": [
                        {
                            "id": f"source-{index}",
                            "title": "z" * 2_000,
                            "sourceType": "web",
                            "url": f"https://example.com/{index}",
                        }
                        for index in range(8)
                    ],
                },
            },
        ],
    )

    context = AgentPromptCompiler(request, _config()).checkpoint_summary(
        2, CHECKPOINT_CONTEXT_TOKEN_BUDGET
    )

    serialized = json.dumps(context, ensure_ascii=False)
    assert historical_prompt_evidence_ref("important-user-fact") in serialized
    assert "Keep the verified TypeScript experience." in serialized


def test_loaded_checkpoint_is_not_rebuilt_just_because_history_is_long() -> None:
    history = _legacy_history()
    request = _request(history)
    loaded = AgentConversationCheckpoint(
        throughMessageId="legacy-assistant-21",
        summary={
            "trust": "untrusted_history_data",
            "events": [
                {
                    "role": "user",
                    "evidenceRef": "evidence-user-1",
                    "text": "Keep this verified constraint.",
                },
            ],
        },
    )
    state = AgentConversationState(
        loaded_checkpoint=loaded,
        active_checkpoint=loaded,
    )

    messages = anyio.run(
        partial(
            prepare_agent_prompt,
            request,
            _config(context_window_tokens=128_000),
            AgentRuntimeContext(conversation_state=state),
        ),
    ).messages

    assert state.active_checkpoint == loaded
    assert "Keep this verified constraint." in json.dumps(messages)


def test_rollover_rebuilds_oversized_checkpoint_at_same_boundary() -> None:
    request = _request(
        [
            {
                "id": "history-user",
                "role": "user",
                "text": "Keep the verified TypeScript experience.",
            },
        ],
        prompt="Continue with this resume.",
    )
    request.resume["basic"]["headline"] = "EXACT CURRENT RESUME SENTINEL"
    loaded = AgentConversationCheckpoint(
        throughMessageId="history-user",
        summary={
            "trust": "untrusted_history_data",
            "events": [
                {
                    "role": "assistant",
                    "text": "obsolete-checkpoint-payload " * 4_000,
                },
            ],
        },
    )
    state = AgentConversationState(
        loaded_checkpoint=loaded,
        active_checkpoint=loaded,
    )

    messages = anyio.run(
        partial(
            prepare_agent_prompt,
            request,
            _config(),
            AgentRuntimeContext(conversation_state=state),
        ),
    ).messages

    serialized = json.dumps(messages, ensure_ascii=False)
    assert state.active_checkpoint is not None
    assert state.active_checkpoint.through_message_id == "history-user"
    assert state.active_checkpoint.summary != loaded.summary
    assert historical_prompt_evidence_ref("history-user") in serialized
    assert "obsolete-checkpoint-payload" not in serialized
    assert "EXACT CURRENT RESUME SENTINEL" in serialized
    assert messages[-1] == {
        "role": "user",
        "content": "Continue with this resume.",
    }
    assert estimate_agent_messages_tokens(messages) <= 2_500


def test_cancellation_does_not_change_checkpoint() -> None:
    async def is_aborted() -> bool:
        return True

    request = _request(_legacy_history())
    loaded = AgentConversationCheckpoint(
        throughMessageId="legacy-assistant-21",
        summary={"trust": "untrusted_history_data", "events": []},
    )
    state = AgentConversationState(
        loaded_checkpoint=loaded,
        active_checkpoint=loaded,
    )

    with pytest.raises(AgentRunAborted):
        anyio.run(
            partial(
                prepare_agent_prompt,
                request,
                _config(),
                AgentRuntimeContext(
                    is_aborted=is_aborted,
                    conversation_state=state,
                ),
            ),
        )

    assert state.active_checkpoint == loaded


def test_cancelled_compilation_keeps_event_loop_and_checkpoint_available(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    loaded = AgentConversationCheckpoint(
        throughMessageId="legacy-assistant-21",
        summary={"trust": "untrusted_history_data", "events": []},
    )
    original_summary = loaded.model_copy(deep=True)
    state = AgentConversationState(loaded_checkpoint=loaded, active_checkpoint=loaded)
    original = compaction._compile_agent_prompt

    def delayed_compile(request, config, checkpoint):
        try:
            assert checkpoint is not loaded
            entered.set()
            assert release.wait(timeout=3)
            checkpoint.summary["events"].append({"text": "Worker-local data"})
            return original(request, config, checkpoint)
        finally:
            finished.set()

    monkeypatch.setattr(compaction, "_compile_agent_prompt", delayed_compile)

    async def scenario():
        task = asyncio.create_task(
            prepare_agent_prompt(
                _request(_legacy_history()),
                _config(),
                AgentRuntimeContext(conversation_state=state),
            ),
        )
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert not task.done()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)

    asyncio.run(scenario())
    assert state.active_checkpoint is loaded
    assert state.loaded_checkpoint is loaded
    assert loaded == original_summary


def test_compaction_prepares_current_material_once(monkeypatch):
    history = [
        {
            "id": f"message-{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "text": "Factual resume context. " * 180,
        }
        for index in range(80)
    ]
    original = message_compiler._current_attachment_payload
    calls = 0

    def counted_material(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        message_compiler, "_current_attachment_payload", counted_material
    )
    runtime = AgentRuntimeContext()
    anyio.run(partial(prepare_agent_prompt, _request(history), _config(), runtime))
    assert runtime.conversation_state.active_checkpoint is not None
    assert calls == 1


def test_context_rollover_handoffs_the_last_historical_user_turn() -> None:
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

    config = _config()
    limits = agent_prompt_limits(request, config)
    assert limits is not None
    exact = AgentPromptCompiler(request, config).build()
    assert estimate_agent_messages_tokens(exact.messages) > limits.trigger_tokens

    runtime = AgentRuntimeContext()
    messages = anyio.run(
        partial(
            prepare_agent_prompt,
            request,
            config,
            runtime,
        ),
    ).messages

    assert estimate_agent_messages_tokens(messages) <= limits.input_tokens
    assert runtime.conversation_state.active_checkpoint is not None
    assert (
        runtime.conversation_state.active_checkpoint.through_message_id == "only-user"
    )
    assert messages[-1] == {"role": "user", "content": "Continue."}
    assert estimate_agent_messages_tokens(messages) <= 2_500


def test_context_rollover_runs_when_an_exact_tail_cannot_reach_the_target() -> None:
    request = _request(
        [
            {
                "id": "large-recent-user",
                "role": "user",
                "text": "Keep this recent context. " + ("word " * 800),
            },
        ],
        prompt="Continue with enough room for tools.",
    )
    config = _config()
    limits = agent_prompt_limits(request, config)
    assert limits is not None
    exact = AgentPromptCompiler(request, config).build()
    assert estimate_agent_messages_tokens(exact.messages) > limits.trigger_tokens

    runtime = AgentRuntimeContext()
    prompt = anyio.run(partial(prepare_agent_prompt, request, config, runtime))

    assert runtime.conversation_state.active_checkpoint is not None
    assert (
        runtime.conversation_state.active_checkpoint.through_message_id
        == "large-recent-user"
    )
    assert estimate_agent_messages_tokens(prompt.messages) <= limits.target_tokens


def test_historical_turns_do_not_replay_old_workspace_snapshots() -> None:
    config = _config(context_window_tokens=32_000)
    second = _request(
        [
            {
                "id": "first-user",
                "role": "user",
                "text": "Create a concise draft.",
            },
            {
                "id": "first-assistant",
                "role": "assistant",
                "text": "The draft is ready.",
            },
        ],
        prompt="Shorten the second bullet.",
        current_id="second-user",
    )
    second.resume["basic"]["headline"] = "AI Frontend Engineer"
    second_prompt = anyio.run(
        partial(prepare_agent_prompt, second, config, AgentRuntimeContext()),
    )

    workspace_messages = [
        message
        for message in second_prompt.messages
        if isinstance(message["content"], str)
        and message["content"].startswith('{"workspaceContext":')
    ]
    serialized = json.dumps(second_prompt.messages, ensure_ascii=False)
    assert len(workspace_messages) == 1
    assert "AI Frontend Engineer" in serialized


def test_current_draft_state_obeys_one_total_budget_without_repeating_resume() -> None:
    request = AgentChatRequest(
        message={"id": "current", "role": "user", "text": "Continue."},
        locale="en",
        resume={"basic": {}, "sections": []},
        draftState={
            "id": "draft-budget",
            "sourceMessageId": "assistant-draft",
            "resume": {
                "basic": {"summary": "current resume content " * 1_000},
                "sections": [],
            },
            "pendingCount": 20,
            "reviewItems": [
                {
                    "id": f"review-{index}",
                    "editIds": [f"edit-{index}"],
                    "status": "pending",
                }
                for index in range(20)
            ],
            "edits": [
                {
                    "id": f"edit-{index}",
                    "title": "Long edit title " * 100,
                    "target": "basic.summary",
                    "reason": "Long edit reason " * 100,
                    "operation": {
                        "type": "replace_field",
                        "path": "basic.summary",
                    },
                }
                for index in range(20)
            ],
            "diffs": [
                {
                    "id": f"diff-{index}",
                    "operationId": f"edit-{index}",
                    "path": "basic.summary",
                    "kind": "changed",
                    "before": "before " * 1_000,
                    "after": "after " * 1_000,
                }
                for index in range(20)
            ],
        },
    )

    state = _current_draft_state(request, token_budget=256)
    assert state is not None
    serialized = json.dumps(state, ensure_ascii=False, separators=(",", ":"))

    assert _estimated_json_tokens(state) <= 256
    assert "resumeOutline" not in state
    assert "before" not in serialized
    assert "after" not in serialized


def test_native_media_token_estimate_is_independent_of_base64_size() -> None:
    def estimate(parts: list[LlmContentPart]) -> int:
        messages: list[LlmInputMessage] = [{"role": "user", "content": parts}]
        return estimate_agent_messages_tokens(messages)

    text: LlmContentPart = {"type": "text", "text": "Review these files."}
    small_image: LlmContentPart = {
        "type": "image",
        "media_type": "image/png",
        "data": "YQ==",
    }
    large_image: LlmContentPart = {**small_image, "data": "A" * 1_000_000}
    small_file: LlmContentPart = {
        "type": "file",
        "filename": "resume.pdf",
        "media_type": "application/pdf",
        "data": "YQ==",
    }
    large_file: LlmContentPart = {**small_file, "data": "A" * 1_000_000}

    assert estimate([text, small_image]) == estimate([text, large_image])
    assert estimate([text, small_file]) == estimate([text, large_file])


def test_plain_text_token_estimate_is_unchanged() -> None:
    assert (
        estimate_agent_messages_tokens(
            [{"role": "user", "content": "ordinary text"}],
        )
        == 11
    )


def test_loaded_checkpoint_projects_only_the_exact_history_tail(monkeypatch):
    history = [
        {
            "id": f"message-{index}",
            "role": "user" if index % 2 == 0 else "assistant",
            "text": "Factual resume context. " * 180,
        }
        for index in range(80)
    ]
    loaded = AgentConversationCheckpoint(
        throughMessageId="message-69",
        summary={"trust": "untrusted_history_data", "events": []},
    )
    counts = []
    original = message_compiler._conversation_entries

    def project_tail(conversation, **kwargs):
        counts.append(len(conversation))
        return original(conversation, **kwargs)

    monkeypatch.setattr(message_compiler, "_conversation_entries", project_tail)
    runtime = AgentRuntimeContext(
        conversation_state=AgentConversationState(active_checkpoint=loaded),
    )
    anyio.run(
        partial(
            prepare_agent_prompt,
            _request(history),
            _config(context_window_tokens=32_768),
            runtime,
        ),
    )
    assert counts == [10]
    assert runtime.conversation_state.active_checkpoint == loaded
