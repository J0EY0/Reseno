"""Regression tests for model-led tool use and natural completion."""

import asyncio
import json
from dataclasses import replace

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
)
from app.services.agent.integrations import web as agent_web
from app.services.agent.runtime import loop as agent_loop
from app.services.agent.runtime import streaming as agent_streaming
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestError,
    LlmStreamEvent,
    LlmTimeoutError,
    LlmToolCall,
    LlmToolValidationError,
    LlmWebSource,
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


def _request(prompt: str) -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="turn-open-agent-loop",
            role="user",
            text=prompt,
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


def _completed_result(
    events: list[agent_loop.AgentToolLoopEvent],
) -> agent_loop.AgentTurnResult:
    completion = events[-1]
    assert isinstance(completion, agent_loop.AgentToolLoopCompleted)
    return completion.result


def _summary_edit(value: str, *, call_id: str = "call-edit") -> LlmToolCall:
    arguments = {
        "edits": [
            {
                "evidenceRefs": ["prompt:current"],
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": value,
                },
            },
        ],
    }
    return LlmToolCall(
        id=call_id,
        name="edit_execute",
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _missing_item_edit() -> LlmToolCall:
    arguments = {
        "edits": [
            {
                "evidenceRefs": ["prompt:current"],
                "operation": {
                    "type": "update_item",
                    "sectionId": "projects",
                    "itemId": "missing",
                    "patch": {"description": "不会被应用"},
                },
            },
        ],
    }
    return LlmToolCall(
        id="call-missing-item",
        name="edit_execute",
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def test_star_advice_naturally_ends_without_a_forced_tool(monkeypatch) -> None:
    async def scenario() -> None:
        model_calls = 0

        async def fake_model_response(*_args, **_kwargs):
            nonlocal model_calls
            model_calls += 1
            response = LlmAssistantMessage(
                content="先补充项目背景、你的具体行动和可验证产出；没有结果数据也不要编造。",
                stop_reason="stop",
            )
            yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request("如何用 STAR 写项目经历？请结合当前项目给建议。"),
                _config(),
            )
        ]
        completion = events[-1]

        assert model_calls == 1
        assert isinstance(completion, agent_loop.AgentToolLoopCompleted)
        assert completion.result.tools == ()
        assert completion.result.terminal_text.startswith("先补充项目背景")
        assert any(
            isinstance(event, agent_loop.AgentToolLoopTerminalText) for event in events
        )

    asyncio.run(scenario())


def test_native_search_hides_local_web_tools_and_keeps_provider_sources(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        source = LlmWebSource(
            id="source-web-current-role",
            title="Current frontend role",
            url="https://jobs.example.com/frontend",
            excerpt="React and TypeScript are required.",
        )

        async def fake_model_response(_config, _prompt, _runtime, tool_schemas):
            assert [schema["function"]["name"] for schema in tool_schemas] == [
                "edit_execute"
            ]
            response = LlmAssistantMessage(
                content="该岗位当前强调 React 与 TypeScript。",
                stop_reason="stop",
                sources=[source],
            )
            yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request("结合最新岗位要求分析简历。"),
                replace(_config(), use_native_web_search=True),
            )
        ]
        result = _completed_result(events)

        assert result is not None
        assert result.tools == ()
        assert result.message is not None
        assert result.message.sources[0].url == source.url
        assert result.message.text == result.terminal_text

    asyncio.run(scenario())


def test_context_transform_runs_before_every_model_turn(monkeypatch) -> None:
    async def scenario() -> None:
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[
                        LlmToolCall(
                            id="call-unknown",
                            name="unknown_tool",
                            arguments={},
                            raw_arguments="{}",
                        ),
                    ],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(content="已完成检查。", stop_reason="stop"),
            ],
        )
        transformed_message_counts: list[int] = []

        def record_transform(_request, _config, prompt):
            transformed_message_counts.append(len(prompt.messages))
            return prompt

        async def fake_model_response(*_args, **_kwargs):
            response = next(responses)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "fit_agent_model_turn_prompt",
            record_transform,
        )
        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request("检查当前简历。"),
                _config(),
            )
        ]

        assert transformed_message_counts == [3, 5]
        assert _completed_result(events).terminal_text == "已完成检查。"

    asyncio.run(scenario())


def test_validated_edit_commits_after_natural_completion(monkeypatch) -> None:
    async def scenario() -> None:
        model_calls = 0
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[_summary_edit("聚焦复杂交互与工程质量。")],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(content="修改草稿已生成。", stop_reason="stop"),
            ],
        )

        async def fake_model_response(_config, prompt, _runtime, _tool_schemas):
            nonlocal model_calls
            model_calls += 1
            if model_calls == 2:
                observation = json.loads(prompt.messages[-1]["content"])
                assert observation["output"] == {
                    "status": "accepted",
                    "editCount": 1,
                }
            response = next(responses)
            if response.content:
                yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(
                    "候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。",
                ),
                _config(),
            )
        ]
        result = _completed_result(events)

        assert result is not None
        assert result.transaction_state == "committed"
        assert len(result.edits) == 1
        assert result.edits[0].operation["value"] == "聚焦复杂交互与工程质量。"
        assert result.terminal_text == "修改草稿已生成。"

    asyncio.run(scenario())


def test_loop_allows_multiple_schema_repairs_before_a_valid_tool_call(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        invalid_calls = [
            LlmToolCall(
                id=f"call-invalid-{index}",
                name="edit_execute",
                arguments={},
                raw_arguments="{}",
            )
            for index in range(2)
        ]
        responses = iter(
            [
                *[
                    LlmAssistantMessage(
                        tool_calls=[tool_call],
                        validation_errors=[
                            LlmToolValidationError(
                                tool_call=tool_call,
                                message="'edits' is a required property",
                            ),
                        ],
                        stop_reason="tool_calls",
                    )
                    for tool_call in invalid_calls
                ],
                LlmAssistantMessage(
                    tool_calls=[_summary_edit("持续修复参数后生成的简介。")],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(content="修改草稿已生成。", stop_reason="stop"),
            ],
        )
        model_calls = 0

        async def fake_model_response(_config, prompt, *_args, **_kwargs):
            nonlocal model_calls
            model_calls += 1
            if 1 < model_calls < 4:
                observation = json.loads(prompt.messages[-1]["content"])
                assert observation["error"] == "TOOL_ARGUMENT_VALIDATION_FAILED"
            response = next(responses)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request("候选人事实：持续改进工程质量。请更新简介。"),
                _config(),
            )
        ]
        result = _completed_result(events)

        assert model_calls == 4
        assert result is not None
        assert result.transaction_state == "committed"
        assert len(result.edits) == 1
        assert result.edits[0].operation["value"] == "持续修复参数后生成的简介。"

    asyncio.run(scenario())


def test_loop_executes_valid_reads_when_a_sibling_call_fails_validation(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        url = "https://example.com/jobs/current-role"
        fetch_call = LlmToolCall(
            id="call-valid-fetch",
            name="web_fetch",
            arguments={"url": url},
            raw_arguments=json.dumps({"url": url}),
        )
        invalid_edit = LlmToolCall(
            id="call-invalid-edit",
            name="edit_execute",
            arguments={},
            raw_arguments="{}",
        )
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[fetch_call, invalid_edit],
                    validation_errors=[
                        LlmToolValidationError(
                            tool_call=invalid_edit,
                            message="'edits' is a required property",
                        ),
                    ],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    content="已读取最新 JD，并指出需要补充的经历。",
                    stop_reason="stop",
                ),
            ],
        )
        fetch_count = 0
        model_calls = 0

        async def fake_fetch(*_args, **_kwargs):
            nonlocal fetch_count
            fetch_count += 1
            return agent_web.WebReference(
                title="Current role",
                excerpt="JD_OBSERVATION_ONLY: React Server Components are required.",
                final_url=url,
                passages=(
                    agent_web.WebPassage(
                        section="Requirements",
                        text=(
                            "JD_OBSERVATION_ONLY: React Server Components are required."
                        ),
                    ),
                ),
            )

        async def fake_model_response(_config, prompt, *_args, **_kwargs):
            nonlocal model_calls
            model_calls += 1
            if model_calls == 2:
                observations = [
                    json.loads(message["content"]) for message in prompt.messages[-2:]
                ]
                assert observations[0]["title"] == "web_fetch"
                assert (
                    "JD_OBSERVATION_ONLY"
                    in observations[0]["output"]["references"][0]["passages"][0]["text"]
                )
                assert observations[1]["error"] == ("TOOL_ARGUMENT_VALIDATION_FAILED")
            response = next(responses)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_web,
            "_async_fetch_web_reference",
            fake_fetch,
        )
        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(f"读取 {url} 后分析当前简历。"),
                _config(),
            )
        ]
        result = _completed_result(events)

        assert fetch_count == 1
        assert result is not None
        assert [tool.id for tool in result.tools] == ["call-valid-fetch"]
        assert all(
            tool.id != "call-invalid-edit"
            for event in events
            if isinstance(event, agent_loop.AgentToolLoopTools)
            for tool in event.tools
        )

    asyncio.run(scenario())


def test_loop_regenerates_a_write_after_reading_same_response_observations(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        url = "https://example.com/jobs/frontend"
        selected_edit = _summary_edit(
            "模型同轮选择的简介。",
            call_id="call-premature-edit",
        )
        regenerated_edit = _summary_edit(
            "聚焦 React 与 TypeScript 的前端工程师。",
            call_id="call-regenerated-edit",
        )
        fetch_call = LlmToolCall(
            id="call-fetch",
            name="web_fetch",
            arguments={"url": url},
            raw_arguments=json.dumps({"url": url}),
        )
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[fetch_call, selected_edit],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    tool_calls=[regenerated_edit],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(content="修改草稿已生成。", stop_reason="stop"),
            ],
        )

        async def fake_fetch(*_args, **_kwargs):
            return agent_web.WebReference(
                title="Frontend role",
                excerpt=(
                    "JD_OBSERVATION_ONLY: the role values React and "
                    "TypeScript experience."
                ),
                final_url=url,
                passages=(
                    agent_web.WebPassage(
                        section="Requirements",
                        text=(
                            "JD_OBSERVATION_ONLY: the role values React and "
                            "TypeScript experience."
                        ),
                    ),
                ),
            )

        model_calls = 0

        async def fake_model_response(_config, prompt, *_args, **_kwargs):
            nonlocal model_calls
            model_calls += 1
            if model_calls == 2:
                observations = [
                    json.loads(message["content"]) for message in prompt.messages[-2:]
                ]
                assert [item["title"] for item in observations] == [
                    "web_fetch",
                    "edit_execute",
                ]
                assert (
                    "JD_OBSERVATION_ONLY"
                    in observations[0]["output"]["references"][0]["passages"][0]["text"]
                )
                assert observations[1]["output"]["status"] == "not_executed"
            if model_calls == 3:
                observation = json.loads(prompt.messages[-1]["content"])
                assert observation["title"] == "edit_execute"
                assert observation["state"] == "output-available"
            response = next(responses)
            if response.content:
                yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_web,
            "_async_fetch_web_reference",
            fake_fetch,
        )
        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(
                    f"候选人事实：我会 React 和 TypeScript。请参考 {url} 更新简介。",
                ),
                _config(),
            )
        ]
        result = _completed_result(events)

        assert result is not None
        assert model_calls == 3
        assert [tool.title for tool in result.tools] == [
            "web_fetch",
            "edit_execute",
        ]
        assert all(
            tool.id != "call-premature-edit"
            for event in events
            if isinstance(event, agent_loop.AgentToolLoopTools)
            for tool in event.tools
        )
        assert len(result.edits) == 1
        assert result.edits[0].operation["value"] == (
            "聚焦 React 与 TypeScript 的前端工程师。"
        )
        assert result.message is not None
        assert len(result.message.sources) == 1
        assert result.message.sources[0].url == url

    asyncio.run(scenario())


def test_loop_runs_independent_read_tools_in_parallel(monkeypatch) -> None:
    async def scenario() -> None:
        first_url = "https://example.com/jobs/frontend"
        second_url = "https://example.com/jobs/design"
        second_started = asyncio.Event()
        fetch_calls = [
            LlmToolCall(
                id="call-fetch-frontend",
                name="web_fetch",
                arguments={"url": first_url},
                raw_arguments=json.dumps({"url": first_url}),
            ),
            LlmToolCall(
                id="call-fetch-design",
                name="web_fetch",
                arguments={"url": second_url},
                raw_arguments=json.dumps({"url": second_url}),
            ),
        ]
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=fetch_calls,
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(content="两个岗位都已读取。", stop_reason="stop"),
            ],
        )

        async def fake_fetch(url: str, *_args, **_kwargs):
            if url == first_url:
                await asyncio.wait_for(second_started.wait(), timeout=0.2)
            else:
                second_started.set()
            return agent_web.WebReference(
                title=url.rsplit("/", 1)[-1],
                excerpt="Current role requirements.",
                final_url=url,
            )

        async def fake_model_response(*_args, **_kwargs):
            response = next(responses)
            if response.content:
                yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_web,
            "_async_fetch_web_reference",
            fake_fetch,
        )
        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(f"比较 {first_url} 和 {second_url}。"),
                _config(),
            )
        ]
        result = _completed_result(events)

        assert result is not None
        assert [tool.title for tool in result.tools] == ["web_fetch", "web_fetch"]
        assert result.terminal_text == "两个岗位都已读取。"

    asyncio.run(scenario())


def test_model_request_timeout_is_not_retried_before_visible_output(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        attempts = 0

        async def timed_out_model_response(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            raise LlmTimeoutError("Model provider request timed out.")
            yield

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            timed_out_model_response,
        )

        with pytest.raises(LlmTimeoutError):
            async for _event in agent_loop.async_iter_agent_tool_call_loop(
                _request(
                    "候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。",
                ),
                _config(),
            ):
                pass

        assert attempts == 1

    asyncio.run(scenario())


def test_model_request_is_not_retried_after_a_visible_delta(monkeypatch) -> None:
    async def scenario() -> None:
        attempts = 0

        async def interrupted_model_response(*_args, **_kwargs):
            nonlocal attempts
            attempts += 1
            yield LlmStreamEvent(type="text_delta", delta="部分回答")
            raise LlmTimeoutError("Model provider request timed out.")

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            interrupted_model_response,
        )

        with pytest.raises(LlmTimeoutError):
            async for _event in agent_loop.async_iter_agent_tool_call_loop(
                _request("诊断这份简历。"),
                _config(),
            ):
                pass

        assert attempts == 1

    asyncio.run(scenario())


def test_empty_natural_completion_rolls_back_pending_edits(monkeypatch) -> None:
    async def scenario() -> None:
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[_summary_edit("聚焦复杂交互与工程质量。")],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(content="", stop_reason="stop"),
            ],
        )
        opened_environments = []
        real_open = agent_loop.ResumeToolEnvironment.open

        class RecordingEnvironmentFactory:
            @staticmethod
            def open(
                request: AgentChatRequest,
                *,
                include_web_tools: bool = True,
            ):
                environment = real_open(
                    request,
                    include_web_tools=include_web_tools,
                )
                opened_environments.append(environment)
                return environment

        async def empty_completion(*_args, **_kwargs):
            response = next(responses)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "ResumeToolEnvironment",
            RecordingEnvironmentFactory,
        )
        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            empty_completion,
        )

        with pytest.raises(
            LlmRequestError,
            match="Model provider returned an empty response",
        ):
            async for _event in agent_loop.async_iter_agent_tool_call_loop(
                _request(
                    "候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。",
                ),
                _config(),
            ):
                pass

        assert len(opened_environments) == 1
        rolled_back = opened_environments[0].close(completed=False)
        assert rolled_back.transaction_state == "rolled_back"
        assert rolled_back.edits == ()

    asyncio.run(scenario())


def test_replayed_recoverable_observation_does_not_end_the_loop(monkeypatch) -> None:
    async def scenario() -> None:
        rejected_call = _missing_item_edit()
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[rejected_call],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    tool_calls=[rejected_call],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    tool_calls=[_summary_edit("聚焦复杂交互与工程质量。")],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(content="修复后的草稿已生成。", stop_reason="stop"),
            ],
        )
        model_calls = 0

        async def fake_model_response(*_args, **_kwargs):
            nonlocal model_calls
            model_calls += 1
            response = next(responses)
            if response.content:
                yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(
                    "候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。",
                ),
                _config(),
            )
        ]
        result = _completed_result(events)

        assert model_calls == 4
        assert result is not None
        assert result.transaction_state == "committed"
        assert len(result.edits) == 1
        assert result.terminal_text == "修复后的草稿已生成。"

    asyncio.run(scenario())


def test_natural_completion_keeps_accepted_edits_after_rejected_followup(
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
                    tool_calls=[_missing_item_edit()],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    content="已生成待确认草稿。",
                    stop_reason="stop",
                ),
            ],
        )

        async def fake_model_response(*_args, **_kwargs):
            response = next(responses)
            if response.content:
                yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        events = [
            event
            async for event in agent_loop.async_iter_agent_tool_call_loop(
                _request(
                    "候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。",
                ),
                _config(),
            )
        ]
        result = _completed_result(events)

        assert result is not None
        assert result.transaction_state == "committed"
        assert len(result.edits) == 1
        assert [tool.state for tool in result.tools] == [
            "output-available",
            "output-error",
        ]
        assert result.message is not None
        assert result.message.draft is not None
        assert not any(
            isinstance(event, agent_loop.AgentToolLoopEdits)
            and event.transaction_state == "rolled_back"
            for event in events
        )

    asyncio.run(scenario())


def test_committed_edit_publishes_the_models_natural_completion(monkeypatch) -> None:
    async def scenario() -> None:
        responses = iter(
            [
                LlmAssistantMessage(
                    tool_calls=[_summary_edit("聚焦复杂交互与工程质量。")],
                    stop_reason="tool_calls",
                ),
                LlmAssistantMessage(
                    content="已根据你提供的事实生成一版简介草稿，请确认后再应用。",
                    stop_reason="stop",
                ),
            ],
        )
        model_calls = 0

        async def fake_model_response(*_args, **_kwargs):
            nonlocal model_calls
            model_calls += 1
            response = next(responses)
            if response.content:
                yield LlmStreamEvent(type="text_delta", delta=response.content)
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        frames = [
            agent_streaming.serialize_agent_event(event)
            async for event in agent_streaming.async_iter_resolved_agent_events(
                _request(
                    "候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。",
                ),
                _config(),
            )
        ]
        done_frame = next(
            frame for frame in frames if frame.startswith("event: message_done")
        )
        payload = json.loads(done_frame.split("data: ", maxsplit=1)[1])

        assert model_calls == 2
        assert payload["message"]["text"] == (
            "已根据你提供的事实生成一版简介草稿，请确认后再应用。"
        )
        assert payload["message"]["transactionState"] == "committed"
        assert len(payload["message"]["edits"]) == 1

    asyncio.run(scenario())


def test_public_text_stream_sends_only_incremental_payloads(monkeypatch) -> None:
    async def scenario() -> None:
        content = "流式文本" * 80

        async def fake_model_response(*_args, **_kwargs):
            for character in content:
                yield LlmStreamEvent(type="text_delta", delta=character)
            yield LlmStreamEvent(
                type="done",
                message=LlmAssistantMessage(
                    content=content,
                    stop_reason="stop",
                ),
            )

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            fake_model_response,
        )

        frames = [
            agent_streaming.serialize_agent_event(event)
            async for event in agent_streaming.async_iter_resolved_agent_events(
                _request("分析这份简历。"),
                _config(),
            )
        ]
        delta_frames = [
            frame for frame in frames if frame.startswith("event: text_delta")
        ]

        assert len(delta_frames) == len(content)
        assert not any(frame.startswith("event: timeline") for frame in frames)
        assert not any(frame.startswith("event: message_delta") for frame in frames)
        assert all(
            '"timelinePartId":"timeline-text-1"' in frame for frame in delta_frames
        )
        assert all('"timeline":' not in frame for frame in delta_frames)
        assert max(map(len, delta_frames)) < 180

        done_frame = next(
            frame for frame in frames if frame.startswith("event: message_done")
        )
        payload = json.loads(done_frame.split("data: ", maxsplit=1)[1])
        assert payload["message"]["text"] == content
        assert payload["message"]["timeline"][0]["text"] == content

    asyncio.run(scenario())


def test_model_turn_limit_rolls_back_and_emits_an_internal_error(monkeypatch) -> None:
    async def scenario() -> None:
        model_calls = 0

        async def repeated_model_response(*_args, **_kwargs):
            nonlocal model_calls
            model_calls += 1
            response = LlmAssistantMessage(
                tool_calls=[_summary_edit("聚焦复杂交互与工程质量。")],
                stop_reason="tool_calls",
            )
            yield LlmStreamEvent(type="done", message=response)

        monkeypatch.setattr(
            agent_loop,
            "_async_iter_model_response",
            repeated_model_response,
        )

        frames = [
            agent_streaming.serialize_agent_event(event)
            async for event in agent_streaming.async_iter_resolved_agent_events(
                _request(
                    "候选人事实：我关注复杂交互与工程质量。请据此优化个人简介。",
                ),
                _config(),
                runtime=AgentRuntimeContext(max_model_turns=1),
            )
        ]
        error_frame = next(
            frame for frame in frames if frame.startswith("event: error")
        )
        error_payload = json.loads(error_frame.split("data: ", maxsplit=1)[1])
        done_frame = next(
            frame for frame in frames if frame.startswith("event: message_done")
        )
        payload = json.loads(done_frame.split("data: ", maxsplit=1)[1])

        assert model_calls == 1
        assert error_payload["errorCode"] == "AGENT_INTERNAL_ERROR"
        assert "模型操作轮次上限" in payload["message"]["text"]
        assert payload["message"]["edits"] == []
        assert payload["message"]["transactionState"] == "rolled_back"
        assert '"transactionState":"rolled_back"' in "".join(frames)

    asyncio.run(scenario())
