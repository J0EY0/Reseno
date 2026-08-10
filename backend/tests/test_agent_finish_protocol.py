import asyncio
import json

import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.runtime import loop as agent_loop
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import AgentLlmConfig, LlmAssistantMessage, LlmToolCall


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


def _request() -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="turn-finish-protocol",
            role="user",
            text="优化个人简介",
        ),
        locale="zh",
        resume={
            "schemaVersion": 2,
            "basic": {
                "name": "",
                "headline": "前端工程师",
                "phone": "",
                "email": "",
                "location": "",
                "avatar": "",
                "summary": "原始简介",
                "customFields": [],
            },
            "sections": [],
        },
    )


def _summary_edit(value: str) -> LlmToolCall:
    arguments = {
        "edits": [
            {
                "title": "更新简介",
                "target": "basic.summary",
                "reason": "让简介更聚焦。",
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": value,
                },
            },
        ],
    }
    return LlmToolCall(
        id="call-edit",
        name="edit_execute",
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _finish(status: str = "ready") -> LlmToolCall:
    arguments = {"status": status, "reason": "本轮处理完成。"}
    return LlmToolCall(
        id=f"call-finish-{status}",
        name="finish",
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def test_edit_is_rolled_back_when_model_ends_without_explicit_finish(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[_summary_edit("聚焦复杂交互与工程质量。")],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    content="修改已完成。",
                    stop_reason="stop",
                ),
            ],
        )

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return next(responses)

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(),
                _config(),
            )
        ]
        runner = events[-1].runner

        assert runner is not None
        assert runner.transaction_state == "rolled_back"
        assert runner.draft_resume["basic"]["summary"] == "原始简介"
        assert runner.edits == []

    asyncio.run(scenario())


def test_edit_is_rolled_back_when_iteration_limit_is_reached(monkeypatch) -> None:
    async def scenario() -> None:
        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                tool_calls=[_summary_edit("不应提交的简介")],
                stop_reason="tool_calls",
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        request = _request().model_copy(
            update={"settings": {"maxReActIterations": 1}},
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                request,
                _config(),
            )
        ]
        runner = events[-1].runner

        assert runner is not None
        assert runner.transaction_state == "rolled_back"
        assert runner.draft_resume["basic"]["summary"] == "原始简介"
        assert runner.edits == []

    asyncio.run(scenario())


def test_edit_commits_after_explicit_ready_finish(monkeypatch) -> None:
    async def scenario() -> None:
        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                tool_calls=[
                    _summary_edit("聚焦复杂交互与工程质量。"),
                    _finish(),
                ],
                stop_reason="tool_calls",
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(),
                _config(),
            )
        ]
        runner = events[-1].runner

        assert runner is not None
        assert runner.finish_status == "ready"
        assert runner.transaction_state == "committed"
        assert runner.draft_resume["basic"]["summary"] == ("聚焦复杂交互与工程质量。")

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid_status", ["", "complete"])
def test_edit_is_rolled_back_when_finish_status_is_invalid(
    monkeypatch,
    invalid_status: str,
) -> None:
    async def scenario() -> None:
        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                tool_calls=[
                    _summary_edit("不应提交的简介"),
                    _finish(invalid_status),
                ],
                stop_reason="tool_calls",
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(),
                _config(),
            )
        ]
        runner = events[-1].runner

        assert runner is not None
        assert runner.finish_status == ""
        assert runner.transaction_state == "rolled_back"
        assert runner.draft_resume["basic"]["summary"] == "原始简介"
        assert runner.edits == []

    asyncio.run(scenario())


def test_plain_answer_without_edits_completes_normally(monkeypatch) -> None:
    async def scenario() -> None:
        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                content="这份简历的项目经历需要补充量化结果。",
                stop_reason="stop",
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(),
                _config(),
            )
        ]
        runner = events[-1].runner

        assert runner is not None
        assert runner.transaction_state == "none"
        assert runner.terminal_text == "这份简历的项目经历需要补充量化结果。"
        assert any(event.kind == "text" and event.terminal for event in events)

    asyncio.run(scenario())


def test_edit_is_rolled_back_when_tool_loop_raises(monkeypatch) -> None:
    async def scenario() -> None:
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[_summary_edit("不应提交的简介")],
                    stop_reason="tool_calls",
                ),
                RuntimeError("provider failed"),
            ],
        )
        created_runners: list[AgentToolRunner] = []
        original_runner_type = agent_loop.AgentToolRunner

        def capture_runner(executor) -> AgentToolRunner:
            runner = original_runner_type(executor)
            created_runners.append(runner)
            return runner

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(agent_loop, "AgentToolRunner", capture_runner)
        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )

        with pytest.raises(RuntimeError, match="provider failed"):
            async for _ in agent_loop.async_iter_agent_tool_call_loop(
                _request(),
                _config(),
            ):
                pass

        assert len(created_runners) == 1
        runner = created_runners[0]
        assert runner.transaction_state == "rolled_back"
        assert runner.draft_resume["basic"]["summary"] == "原始简介"
        assert runner.edits == []

    asyncio.run(scenario())
