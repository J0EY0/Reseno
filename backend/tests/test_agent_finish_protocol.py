import asyncio
import json
import sqlite3

import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.integrations import WebSearchReference, WebSearchResult
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


def test_read_failure_after_successful_edit_rolls_back_with_research_reason(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = _request().model_copy(
            update={
                "message": AgentConversationItem(
                    id="turn-edit-then-research-timeout",
                    role="user",
                    text=(
                        "候选人事实：我关注复杂交互与工程质量。"
                        "请针对前端工程师岗位优化个人简介。"
                    ),
                ),
            },
        )
        web_call = LlmToolCall(
            id="call-web-timeout-after-edit",
            name="web_search",
            arguments={
                "queries": [
                    "frontend engineer responsibilities",
                    "frontend engineer skills",
                ],
                "maxResults": 10,
                "purpose": "target_context",
            },
            raw_arguments=json.dumps(
                {
                    "queries": [
                        "frontend engineer responsibilities",
                        "frontend engineer skills",
                    ],
                    "maxResults": 10,
                    "purpose": "target_context",
                },
            ),
        )

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                tool_calls=[
                    _summary_edit("聚焦复杂交互与工程质量。"),
                    web_call,
                ],
                stop_reason="tool_calls",
            )

        def timed_out_search(
            queries: list[str],
            max_results: int,
        ) -> WebSearchReference:
            return WebSearchReference(
                query=queries[0],
                results=(),
                query_count=len(queries),
                result_count=0,
                error="Web search exceeded its operation time budget.",
                timed_out=True,
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        monkeypatch.setattr(
            "app.services.agent._search_web_reference_summary",
            timed_out_search,
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
        assert [tool.title for tool in runner.tools] == ["edit_execute", "web_search"]
        assert runner.tools[-1].state == "output-error"
        assert runner.transaction_state == "rolled_back"
        assert runner.edits == []
        assert "超时" in runner.terminal_text
        assert "重试" in runner.terminal_text
        message = runner.build_message()
        assert message.transaction_state == "rolled_back"
        assert "超时" in message.text
        assert "重试" in message.text
        assert "草稿" not in message.text

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


def test_read_only_tool_terminal_text_still_uses_citation_finalizer(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = _request().model_copy(
            update={
                "message": AgentConversationItem(
                    id="turn-read-only-research-citation-finalizer",
                    role="user",
                    text="搜索 AI 前端工程师的公开要求，只做研究，不修改简历。",
                ),
            },
        )
        web_arguments = {
            "queries": ["AI frontend engineer requirements"],
            "maxResults": 5,
            "purpose": "target_context",
        }
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id="call-web-research-citation",
                            name="web_search",
                            arguments=web_arguments,
                            raw_arguments=json.dumps(web_arguments),
                        ),
                    ],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    content="example.test: React and TypeScript requirements",
                    stop_reason="stop",
                ),
            ],
        )
        finalizer_calls = 0
        final_payload = {}
        completed_messages = []

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return next(responses)

        async def fake_final_stream(_config, messages, _runtime):
            nonlocal finalizer_calls, final_payload
            finalizer_calls += 1
            workspace_message = next(
                message
                for message in reversed(messages)
                if message["role"] == "user"
                and isinstance(message["content"], str)
                and message["content"].startswith('{"workspaceContext":')
            )
            final_payload = json.loads(workspace_message["content"])[
                "workspaceContext"
            ]
            yield LlmStreamEvent(
                type="text_delta",
                delta=(
                    '<citation source_ids="source-jd-search">'
                    "公开样本反复提到 React 与 TypeScript"
                    "</citation>。"
                ),
            )
            yield LlmStreamEvent(
                type="done",
                message=LlmAssistantMessage(stop_reason="stop"),
            )

        def fake_search(
            queries: list[str],
            max_results: int,
        ) -> WebSearchReference:
            return WebSearchReference(
                query=queries[0],
                results=(
                    WebSearchResult(
                        title="AI Frontend Engineer",
                        url="https://example.test/jobs/ai-frontend",
                        excerpt="Requirements include React and TypeScript.",
                    ),
                ),
                query_count=len(queries),
                result_count=1,
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        monkeypatch.setattr(
            "app.services.agent._search_web_reference_summary",
            fake_search,
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
                    request,
                    conn,
                    completed_messages.append,
                )
            ]
        finally:
            conn.close()

        assert finalizer_calls == 1
        assert final_payload["citationSources"][0]["id"] == "source-jd-search"
        assert len(completed_messages) == 1
        assert "<citation " in completed_messages[0].text
        assert "example.test:" not in completed_messages[0].text
        assert "example.test:" not in "".join(frames)

    asyncio.run(scenario())


def test_control_failure_after_web_success_keeps_deterministic_error(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = _request().model_copy(
            update={
                "message": AgentConversationItem(
                    id="turn-web-success-then-control-failure",
                    role="user",
                    text="搜索 AI 前端工程师的公开要求，只做研究，不修改简历。",
                ),
            },
        )
        web_arguments = {
            "queries": ["AI frontend engineer requirements"],
            "maxResults": 5,
            "purpose": "target_context",
        }
        target_arguments = {
            "mode": "replace",
            "context": {
                "kind": "employment",
                "target": "量子计算研究员",
            },
        }
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id="call-web-before-control-failure",
                            name="web_search",
                            arguments=web_arguments,
                            raw_arguments=json.dumps(web_arguments),
                        ),
                    ],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id="call-ungrounded-target-after-web",
                            name="update_target_context",
                            arguments=target_arguments,
                            raw_arguments=json.dumps(target_arguments),
                        ),
                    ],
                    stop_reason="tool_calls",
                ),
            ],
        )
        completed_messages = []

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return next(responses)

        async def unexpected_final_stream(*_args, **_kwargs):
            raise AssertionError("a terminal control failure must not be rewritten")
            yield

        def fake_search(
            queries: list[str],
            max_results: int,
        ) -> WebSearchReference:
            return WebSearchReference(
                query=queries[0],
                results=(
                    WebSearchResult(
                        title="AI Frontend Engineer",
                        url="https://example.test/jobs/ai-frontend",
                        excerpt="Requirements include React and TypeScript.",
                    ),
                ),
                query_count=len(queries),
                result_count=1,
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        monkeypatch.setattr(
            "app.services.agent._search_web_reference_summary",
            fake_search,
        )
        monkeypatch.setattr(
            streaming,
            "resolve_agent_llm_config",
            lambda *_args, **_kwargs: _config(),
        )
        monkeypatch.setattr(
            streaming,
            "_complete_chat_stream_events",
            unexpected_final_stream,
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
                    request,
                    conn,
                    completed_messages.append,
                )
            ]
        finally:
            conn.close()

        assert len(completed_messages) == 1
        message = completed_messages[0]
        assert message.transaction_state == "none"
        assert message.tools[-1].state == "output-error"
        assert "目标信息" in message.text
        assert "重试" in message.text
        assert "量子计算研究员" not in message.text
        assert "AGENT_INTERNAL_ERROR" not in "".join(frames)

    asyncio.run(scenario())


def test_tool_loop_continues_until_finish_without_iteration_limit(monkeypatch) -> None:
    async def scenario() -> None:
        response_count = 0

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            nonlocal response_count
            response_count += 1
            if response_count <= 9:
                return LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id=f"call-analysis-{response_count}",
                            name="resume_analysis",
                            arguments={},
                            raw_arguments="{}",
                        ),
                    ],
                    stop_reason="tool_calls",
                )
            return LlmAssistantMessage(tool_calls=[_finish()], stop_reason="tool_calls")

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
        assert response_count == 10
        assert runner.finish_status == "ready"
        assert runner.transaction_state == "none"
        assert runner.draft_resume["basic"]["summary"] == "原始简介"

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
                    _summary_edit("聚焦复杂交互与工程质量。"),
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
