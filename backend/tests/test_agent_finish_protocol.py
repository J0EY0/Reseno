import asyncio
import json
import sqlite3

import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.runtime import loop as agent_loop
from app.services.agent.runtime import streaming
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmStreamEvent,
    LlmToolCall,
)


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
            text=("候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。"),
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


def test_edit_is_rolled_back_when_controlled_finish_decision_is_missing(
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
                LlmAssistantMessage(
                    content="草稿已经生成。",
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
        assert runner.terminal_text == ""
        assert runner.build_message().text == "未能生成有效草稿，本轮未应用任何修改。"

    asyncio.run(scenario())


def test_missing_finish_is_recovered_before_stream_publishes_draft(
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
                    content="草稿已生成。",
                    stop_reason="stop",
                ),
                LlmAssistantMessage(
                    tool_calls=[_finish()],
                    stop_reason="tool_calls",
                ),
            ],
        )
        tool_response_count = 0
        requested_tool_names = []
        completed_messages = []

        async def fake_tool_response(
            _config,
            _messages,
            _runtime,
            tool_schemas,
        ) -> LlmAssistantMessage:
            nonlocal tool_response_count
            tool_response_count += 1
            requested_tool_names.append(
                [schema["function"]["name"] for schema in tool_schemas],
            )
            return next(responses)

        async def fake_final_stream(*_args, **_kwargs):
            yield LlmStreamEvent(
                type="text_delta",
                delta="已生成可预览草稿。",
            )
            yield LlmStreamEvent(
                type="done",
                message=LlmAssistantMessage(stop_reason="stop"),
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda *_args, **_kwargs: _config(),
        )
        monkeypatch.setattr(
            streaming,
            "_complete_chat_stream_events",
            fake_final_stream,
        )
        monkeypatch.setattr(
            "app.services.agent_sessions.persist_agent_user_message",
            lambda *_args, **_kwargs: None,
        )

        conn = sqlite3.connect(":memory:")
        try:
            frames = [
                frame
                async for frame in streaming.async_stream_agent_response(
                    _request(),
                    conn,
                    completed_messages.append,
                )
            ]
        finally:
            conn.close()

        assert tool_response_count == 3
        assert requested_tool_names[-1] == ["finish"]
        assert len(completed_messages) == 1
        message = completed_messages[0]
        assert message.transaction_state == "committed"
        assert len(message.edits) == 1
        assert message.edits[0].operation["value"] == "聚焦复杂交互与工程质量。"
        assert message.text == "已生成可预览草稿。"
        assert "草稿已生成。" not in message.text
        assert any('"transactionState":"committed"' in frame for frame in frames)

    asyncio.run(scenario())


def test_tool_action_narration_is_not_published_with_final_stream(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                content="内部旁白：先诊断问题，再执行修改。",
                tool_calls=[
                    _summary_edit("聚焦复杂交互与工程质量。"),
                    _finish(),
                ],
                stop_reason="tool_calls",
            )

        async def fake_final_stream(*_args, **_kwargs):
            yield LlmStreamEvent(
                type="text_delta",
                delta="已精准改写个人简介，可在草稿中预览。",
            )
            yield LlmStreamEvent(
                type="done",
                message=LlmAssistantMessage(stop_reason="stop"),
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda *_args, **_kwargs: _config(),
        )
        monkeypatch.setattr(
            streaming,
            "_complete_chat_stream_events",
            fake_final_stream,
        )
        monkeypatch.setattr(
            "app.services.agent_sessions.persist_agent_user_message",
            lambda *_args, **_kwargs: None,
        )

        completed_messages = []
        conn = sqlite3.connect(":memory:")
        try:
            frames = [
                frame
                async for frame in streaming.async_stream_agent_response(
                    _request(),
                    conn,
                    completed_messages.append,
                )
            ]
        finally:
            conn.close()

        final_text = "已精准改写个人简介，可在草稿中预览。"
        internal_narration = "内部旁白：先诊断问题，再执行修改。"
        assert len(completed_messages) == 1
        assert completed_messages[0].text == final_text
        assert internal_narration not in "".join(frames)

        message_done = next(
            frame for frame in frames if frame.startswith("event: message_done")
        )
        payload = json.loads(
            next(
                line.removeprefix("data: ")
                for line in message_done.splitlines()
                if line.startswith("data: ")
            ),
        )
        assert payload["message"]["text"] == final_text

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


def test_read_only_resume_diagnosis_runs_analysis_before_answer(monkeypatch) -> None:
    async def scenario() -> None:
        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                content="headline 为空，项目字段需要整理。",
                stop_reason="stop",
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        request = _request().model_copy(
            update={
                "message": AgentConversationItem(
                    id="turn-read-only-resume-diagnosis",
                    role="user",
                    text=(
                        "先只做诊断，不要修改简历，也不要检索岗位。"
                        "请逐模块指出 headline、实习、项目、技能的问题。"
                    ),
                ),
            },
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
        assert [tool.title for tool in runner.tools] == ["resume_analysis"]
        assert runner.tools[0].state == "output-available"
        assert runner.terminal_text == ""

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
