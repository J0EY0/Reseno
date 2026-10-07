import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationCheckpoint
from app.schemas.agent_settings import AgentSettings
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.runtime import messages as agent_messages
from app.services.agent.runtime.messages import AgentPromptCompiler
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
    openai_responses,
)
from app.services.llm.common import chat_completion_params
from app.services.llm.types import AgentLlmConfig, LlmPrompt


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="agent-prompt-cache-test",
        name="Prompt cache test",
        provider="openai",
        model="gpt-5.6",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
        provider_kind="cloud",
        api_family="openai_responses",
    )


def _request(**overrides: Any) -> AgentChatRequest:
    values: dict[str, Any] = {
        "message": {
            "id": "current-user",
            "role": "user",
            "text": "Review the project section.",
        },
        "messages": [
            {"id": "old-user", "role": "user", "text": "I use Python."},
            {"id": "old-answer", "role": "assistant", "text": "Recorded."},
            {"id": "recent-user", "role": "user", "text": "I also use SQLite."},
            {
                "id": "recent-answer",
                "role": "assistant",
                "text": "The project facts are ready.",
            },
        ],
        "locale": "zh",
        "resume": {"basic": {"summary": "Backend engineer."}, "sections": []},
    }
    values.update(overrides)
    return AgentChatRequest.model_validate(values)


def _checkpoint() -> AgentConversationCheckpoint:
    return AgentConversationCheckpoint(
        throughMessageId="old-answer",
        summary={
            "trust": "untrusted_history_data",
            "events": [{"role": "user", "text": "I use Python."}],
        },
    )


def _compile(
    monkeypatch: pytest.MonkeyPatch,
    request: AgentChatRequest,
    day: str = "2026-10-07",
) -> LlmPrompt:
    today = date.fromisoformat(day)
    monkeypatch.setattr(agent_messages, "date", SimpleNamespace(today=lambda: today))
    return AgentPromptCompiler(request, _config()).build(_checkpoint())


def _workspace(prompt: LlmPrompt) -> dict[str, Any]:
    return json.loads(str(prompt.messages[-2]["content"]))["workspaceContext"]


@pytest.mark.parametrize(
    ("day", "language", "behavior", "resume_summary", "with_draft"),
    [
        ("2026-10-08", "zh", "balanced", "Backend engineer.", False),
        ("2026-10-07", "en", "balanced", "Backend engineer.", False),
        ("2026-10-07", "zh", "strict", "Backend engineer.", False),
        ("2026-10-07", "zh", "aggressive", "Backend engineer.", False),
        ("2026-10-07", "zh", "balanced", "Python developer.", False),
        ("2026-10-07", "zh", "balanced", "Backend engineer.", True),
    ],
    ids=["date", "language", "strict", "aggressive", "resume", "draft"],
)
def test_runtime_changes_preserve_checkpoint_and_existing_history_prefix(
    monkeypatch: pytest.MonkeyPatch,
    day: str,
    language: str,
    behavior: str,
    resume_summary: str,
    with_draft: bool,
) -> None:
    first_request = _request()
    first = _compile(monkeypatch, first_request)
    draft = (
        {
            "id": "pending-draft",
            "resume": {"basic": {"summary": "Draft candidate."}, "sections": []},
            "pendingCount": 1,
            "reviewItems": [
                {"id": "review-summary", "editIds": ["edit-summary"]},
            ],
        }
        if with_draft
        else None
    )
    second_request = prepare_agent_request(
        _request(
            message={
                "id": "next-user",
                "role": "user",
                "text": "Continue with the skills section.",
            },
            messages=[
                *[item.model_dump(mode="json") for item in first_request.messages],
                first_request.message.model_dump(mode="json"),
                {"id": "current-answer", "role": "assistant", "text": "Reviewed."},
            ],
            resume={"basic": {"summary": resume_summary}, "sections": []},
            draftState=draft,
        ),
        AgentSettings.model_validate(
            {"responseLanguage": language, "behaviorMode": behavior},
        ),
    )

    second = _compile(monkeypatch, second_request, day)

    prefix_count = len(first.messages) - 2
    assert first.messages[0]["role"] == "system"
    assert "conversationCheckpoint" in str(first.messages[1]["content"])
    assert first.messages[prefix_count - 1]["role"] == "user"
    assert json.dumps(second.messages[:prefix_count]) == json.dumps(
        first.messages[:prefix_count],
    )
    assert set(first.stable_prefix_message_counts[:-1]).issubset(
        second.stable_prefix_message_counts,
    )
    assert second.messages[prefix_count]["content"] == first_request.message.text
    assert second.messages[-1]["content"] == second_request.message.text
    workspace = _workspace(second)
    assert workspace["currentDate"] == day
    assert workspace["responseLanguage"] == {"en": "English", "zh": "Chinese"}[language]
    assert workspace["behaviorMode"] == behavior
    assert workspace["resume"]["basic"]["summary"] == (
        "Draft candidate." if with_draft else resume_summary
    )
    current_draft = workspace["conversationState"]["currentDraft"]
    if with_draft:
        assert current_draft["id"] == "pending-draft"
        assert current_draft["pendingCount"] == 1
    else:
        assert current_draft is None
    assert _workspace(first) != workspace


def _wire_prompt(provider: str, prompt: LlmPrompt) -> tuple[Any, list[dict[str, Any]]]:
    config = _config()
    if provider == "openai":
        payload = openai_responses.responses_params(config, prompt)
        return payload["instructions"], payload["input"]
    if provider == "anthropic":
        payload = anthropic_messages._payload(
            replace(
                config,
                provider="anthropic",
                api_family="anthropic_messages",
                base_url="https://api.anthropic.com/v1",
                model="claude-sonnet-4-6",
            ),
            prompt.messages,
        )
        return payload["system"], payload["messages"]
    payload = google_gemini.gemini_payload(
        replace(config, provider="google", api_family="google_gemini"),
        prompt.messages,
    )
    return payload["system_instruction"], payload["input"]


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_provider_payload_keeps_runtime_values_after_stable_history(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    first = _compile(monkeypatch, _request())
    second = _compile(
        monkeypatch,
        prepare_agent_request(
            _request(),
            AgentSettings(responseLanguage="en", behaviorMode="aggressive"),
        ),
        "2026-10-08",
    )

    first_system, first_items = _wire_prompt(provider, first)
    second_system, second_items = _wire_prompt(provider, second)

    assert first_system == second_system
    assert first_items[:-2] == second_items[:-2]
    assert first_items[-1] == second_items[-1]
    assert first_items[-2] != second_items[-2]
    stable_wire = json.dumps([second_system, second_items[:-2]])
    assert "2026-10-08" not in stable_wire
    assert "workspaceContext" not in json.dumps(second_items[:-2])
    assert "2026-10-08" in json.dumps(second_items[-2])


@pytest.mark.parametrize("provider", ["openai", "qwen"])
def test_compiled_cache_boundaries_survive_tool_loop_appends(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    prompt = _compile(monkeypatch, _request())
    original_count = len(prompt.messages)
    assert prompt.stable_prefix_message_counts[-1] == original_count
    assert original_count - 2 in prompt.stable_prefix_message_counts
    assert original_count - 1 not in prompt.stable_prefix_message_counts
    prompt.messages.extend(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-review",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": "{}"},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call-review", "content": "Reviewed."},
        ],
    )

    if provider == "openai":
        items = openai_responses.responses_params(_config(), prompt)["input"]
        marked_counts = tuple(
            index + 2
            for index, item in enumerate(items)
            if isinstance(item.get("content"), list)
            and "prompt_cache_breakpoint" in item["content"][-1]
        )
    else:
        items = chat_completion_params(
            replace(
                _config(),
                provider="qwen",
                api_family="openai_compatible_chat",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="qwen3.7-plus",
            ),
            prompt,
            stream=False,
        )["messages"]
        marked_counts = tuple(
            index + 1
            for index, item in enumerate(items)
            if isinstance(item.get("content"), list)
            and "cache_control" in item["content"][-1]
        )

    expected_counts = prompt.stable_prefix_message_counts
    if provider == "qwen":
        expected_counts = expected_counts[-4:]
    assert marked_counts == expected_counts
    assert marked_counts[-1] == original_count
