import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.schemas.agent_settings import (
    AgentBehaviorMode,
    AgentConfirmationMode,
    AgentResponseLanguage,
    normalize_agent_settings,
)
from app.services.agent.environment import ResumeToolEnvironment
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.runtime.messages import build_agent_messages
from app.services.agent_runs import AgentRunManager
from app.services.llm import AgentLlmConfig


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="test-model",
        name="test-model",
        provider="openai",
        model="test-model",
        base_url="https://example.com/v1",
        api_key="test-key",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
    )


def _request(*, locale: str = "zh") -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id=f"turn-agent-preferences-{locale}",
            role="user",
            text="优化个人简介",
        ),
        locale=locale,
        resume={
            "basic": {"summary": "已有简介"},
            "sections": [],
        },
    )


def test_agent_settings_normalize_each_field_independently() -> None:
    settings = normalize_agent_settings(
        {
            "defaultModelId": "llm-primary",
            "responseLanguage": "unsupported",
            "behaviorMode": "strict",
            "confirmationMode": "suggestOnly",
        },
    )

    assert settings.default_model_id == "llm-primary"
    assert settings.response_language == AgentResponseLanguage.FOLLOW
    assert settings.behavior_mode == AgentBehaviorMode.STRICT
    assert settings.confirmation_mode == AgentConfirmationMode.SUGGEST_ONLY


def test_prepared_agent_request_freezes_settings_for_one_turn() -> None:
    first_turn = prepare_agent_request(
        _request(locale="en"),
        normalize_agent_settings(
            {
                "responseLanguage": "zh",
                "behaviorMode": "strict",
                "confirmationMode": "always",
            },
        ),
    )
    next_turn = prepare_agent_request(
        _request(locale="zh"),
        normalize_agent_settings(
            {
                "responseLanguage": "en",
                "behaviorMode": "aggressive",
                "confirmationMode": "suggestOnly",
            },
        ),
    )

    assert first_turn.locale == "zh"
    assert first_turn.execution_profile is not None
    assert first_turn.execution_profile.response_locale == "zh"
    assert first_turn.execution_profile.behavior_mode == AgentBehaviorMode.STRICT
    assert (
        first_turn.execution_profile.confirmation_mode == AgentConfirmationMode.ALWAYS
    )

    assert next_turn.locale == "en"
    assert next_turn.execution_profile is not None
    assert next_turn.execution_profile.response_locale == "en"
    assert next_turn.execution_profile.behavior_mode == AgentBehaviorMode.AGGRESSIVE
    assert (
        next_turn.execution_profile.confirmation_mode
        == AgentConfirmationMode.SUGGEST_ONLY
    )


def test_follow_language_uses_current_request_locale() -> None:
    request = prepare_agent_request(
        _request(locale="en"),
        normalize_agent_settings({"responseLanguage": "follow"}),
    )

    assert request.locale == "en"
    assert request.execution_profile is not None
    assert request.execution_profile.response_locale == "en"


def test_runtime_prompt_uses_frozen_preferences_without_settings_payload() -> None:
    request = prepare_agent_request(
        _request(locale="zh"),
        normalize_agent_settings(
            {
                "responseLanguage": "en",
                "behaviorMode": "aggressive",
            },
        ),
    )

    messages = build_agent_messages(request, _config())
    workspace_message = next(
        message
        for message in reversed(messages)
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"workspaceContext":')
    )
    payload = json.loads(workspace_message["content"])["workspaceContext"]
    system_prompt = messages[0]["content"]

    assert payload["responseLanguage"] == "English"
    assert "agentSettings" not in payload
    assert "`responseLanguage`: Use English" in system_prompt
    assert "`behaviorMode`: Use an assertive editing posture" in system_prompt
    assert "confirmationMode" not in system_prompt


def test_suggest_only_profile_removes_write_tools() -> None:
    request = prepare_agent_request(
        _request(),
        normalize_agent_settings({"confirmationMode": "suggestOnly"}),
    )

    environment = ResumeToolEnvironment.open(request)
    tool_names = {
        str(schema.get("function", {}).get("name") or "")
        for schema in environment.tool_schemas
    }

    assert tool_names == {"web_search", "web_fetch"}


def test_chat_route_freezes_persisted_settings_for_each_turn(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[AgentChatRequest] = []

    async def fake_start(
        _manager: AgentRunManager,
        request: AgentChatRequest,
    ) -> SimpleNamespace:
        captured_requests.append(request)
        return SimpleNamespace(id=f"run-{len(captured_requests)}")

    async def fake_subscribe(
        _manager: AgentRunManager,
        _run_id: str,
        *,
        after: int = 0,
    ):
        del after
        if False:
            yield ""

    monkeypatch.setattr(AgentRunManager, "start", fake_start)
    monkeypatch.setattr(AgentRunManager, "subscribe", fake_subscribe)

    first_settings = {
        "responseLanguage": "zh",
        "behaviorMode": "strict",
        "confirmationMode": "suggestOnly",
    }
    client.put(
        "/api/workspace/user-settings?locale=zh",
        json={"settings": {"agentSettings": first_settings}},
    )
    first_response = client.post(
        "/api/agent/chat",
        json={
            "message": {
                "id": "turn-agent-preferences-route-first",
                "role": "user",
                "text": "优化个人简介",
            },
            "locale": "en",
            "resume": {"basic": {}, "sections": []},
            # Legacy client values must not override persisted preferences.
            "settings": {"confirmationMode": "always"},
        },
    )

    second_settings = {
        "responseLanguage": "en",
        "behaviorMode": "aggressive",
        "confirmationMode": "always",
    }
    client.put(
        "/api/workspace/user-settings?locale=zh",
        json={"settings": {"agentSettings": second_settings}},
    )
    second_response = client.post(
        "/api/agent/chat",
        json={
            "message": {
                "id": "turn-agent-preferences-route-second",
                "role": "user",
                "text": "优化个人简介",
            },
            "locale": "zh",
            "resume": {"basic": {}, "sections": []},
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(captured_requests) == 2

    first_profile = captured_requests[0].execution_profile
    second_profile = captured_requests[1].execution_profile
    assert first_profile is not None
    assert second_profile is not None
    assert first_profile.response_locale == "zh"
    assert first_profile.behavior_mode == AgentBehaviorMode.STRICT
    assert first_profile.confirmation_mode == AgentConfirmationMode.SUGGEST_ONLY
    assert second_profile.response_locale == "en"
    assert second_profile.behavior_mode == AgentBehaviorMode.AGGRESSIVE
    assert second_profile.confirmation_mode == AgentConfirmationMode.ALWAYS
