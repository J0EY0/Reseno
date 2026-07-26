import asyncio
import json

from app.schemas.agent import AgentChatRequest
from app.services.agent.editing.operations import (
    _model_edit_suggestions_with_diagnostics,
)
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.runtime import loop as agent_loop
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import AgentLlmConfig, LlmAssistantMessage, LlmToolCall


def _runner() -> AgentToolRunner:
    request = AgentChatRequest(
        prompt="优化项目经历",
        locale="zh",
        resume={
            "basic": {"headline": "前端工程师", "summary": "原始简介"},
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "layout": "timeline",
                    "items": [
                        {
                            "id": "project-1",
                            "title": "ResuMate",
                            "description": "原始描述",
                            "highlights": ["原始要点"],
                        },
                    ],
                },
            ],
        },
    )
    return AgentToolRunner(AgentPlanExecutor(request))


def _tool_call(call_id: str, edits: list[dict]) -> LlmToolCall:
    arguments = {"edits": edits}
    return LlmToolCall(
        id=call_id,
        name="edit_execute",
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _plan_tool_call(call_id: str, steps: list[dict]) -> LlmToolCall:
    arguments = {"steps": steps}
    return LlmToolCall(
        id=call_id,
        name="edit_plan",
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _replace_summary(value: str) -> dict:
    return {
        "title": "更新简介",
        "target": "basic.summary",
        "reason": "让简介更聚焦。",
        "operation": {
            "type": "replace_field",
            "path": "basic.summary",
            "value": value,
        },
    }


def test_edit_batch_is_atomic_when_one_operation_is_invalid() -> None:
    runner = _runner()
    original_resume = runner.draft_resume.copy()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "call-invalid-batch",
            [
                _replace_summary("聚焦复杂交互与工程质量。"),
                {
                    "title": "更新不存在的项目",
                    "target": "sections.project.items.missing",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "missing",
                        "patch": {"description": "不会被应用"},
                    },
                },
            ],
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["retryable"] is True
    assert runner.draft_resume == original_resume
    assert runner.edits == []
    assert runner.semantic_retry_pending is True


def test_edit_plan_rejects_the_whole_batch_when_one_operation_is_invalid() -> None:
    runner = _runner()
    original_resume = runner.draft_resume.copy()

    tool, _ = runner._run_local_tool(
        _plan_tool_call(
            "call-invalid-plan",
            [
                {
                    "action": "replace_field",
                    "target": "basic.summary",
                    "reason": "让简介更聚焦。",
                    "operation": _replace_summary(
                        "聚焦复杂交互与工程质量。",
                    )["operation"],
                },
                {
                    "action": "update_item",
                    "target": "sections.project.items.missing",
                    "reason": "更新目标项目。",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "missing",
                        "patch": {"description": "不会被应用"},
                    },
                },
            ],
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["rejectedEditCount"] == 1
    assert tool.output["fullBatchRequired"] is True
    assert runner.plan == []
    assert runner.planned_edits == []
    assert runner.draft_resume == original_resume
    assert runner.semantic_retry_pending is True


def test_finish_stops_later_tool_calls_from_the_same_provider_response(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            prompt="优化个人简介",
            locale="zh",
            resume={
                "basic": {"headline": "前端工程师", "summary": "原始简介"},
                "sections": [],
            },
        )
        config = AgentLlmConfig(
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
        response_count = 0

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            nonlocal response_count
            response_count += 1
            return LlmAssistantMessage(
                tool_calls=[
                    LlmToolCall(
                        id="call-finish",
                        name="finish",
                        arguments={"status": "ready", "reason": "修改已完成。"},
                        raw_arguments="{}",
                    ),
                    _tool_call(
                        "call-after-finish",
                        [_replace_summary("不应被应用")],
                    ),
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
                request,
                config,
            )
        ]
        runner = events[-1].runner

        assert response_count == 1
        assert runner is not None
        assert runner.finished is True
        assert runner.draft_resume["basic"]["summary"] == "原始简介"
        assert runner.edits == []
        assert runner.tools == []

    asyncio.run(scenario())


def test_quality_rejection_defers_same_response_finish_for_one_repair(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            prompt="优化项目经历",
            locale="zh",
            resume={
                "basic": {"headline": "前端工程师", "summary": "原始简介"},
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "layout": "timeline",
                        "items": [
                            {
                                "id": "project-1",
                                "title": "ResuMate",
                                "description": "原始描述",
                                "highlights": ["原始要点"],
                            },
                        ],
                    },
                ],
            },
        )
        config = AgentLlmConfig(
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
        response_count = 0

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            nonlocal response_count
            response_count += 1
            if response_count == 1:
                return LlmAssistantMessage(
                    tool_calls=[
                        _tool_call(
                            "call-quality-rejected",
                            [
                                _replace_summary("聚焦复杂交互与工程质量。"),
                                {
                                    "title": "更新项目描述",
                                    "target": "sections.project.items.project-1",
                                    "operation": {
                                        "type": "update_item",
                                        "sectionId": "project",
                                        "itemId": "project-1",
                                        "patch": {
                                            "subtitle": "AI 简历编辑器",
                                            "description": "ResuMate AI 简历编辑器",
                                        },
                                    },
                                },
                            ],
                        ),
                        LlmToolCall(
                            id="call-premature-finish",
                            name="finish",
                            arguments={"status": "ready", "reason": "修改已完成。"},
                            raw_arguments="{}",
                        ),
                    ],
                    stop_reason="tool_calls",
                )

            return LlmAssistantMessage(
                tool_calls=[
                    _tool_call(
                        "call-quality-repair",
                        [
                            _replace_summary("聚焦复杂交互与工程质量。"),
                            {
                                "title": "更新项目描述",
                                "target": "sections.project.items.project-1",
                                "operation": {
                                    "type": "update_item",
                                    "sectionId": "project",
                                    "itemId": "project-1",
                                    "patch": {
                                        "subtitle": "AI 简历编辑器",
                                        "description": (
                                            "面向结构化简历编辑与预览工作流。"
                                        ),
                                    },
                                },
                            },
                        ],
                    ),
                    LlmToolCall(
                        id="call-finish-after-repair",
                        name="finish",
                        arguments={"status": "ready", "reason": "修改已完成。"},
                        raw_arguments="{}",
                    ),
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
                request,
                config,
            )
        ]
        runner = events[-1].runner
        edit_events = [event for event in events if event.kind == "edits"]

        assert response_count == 2
        assert runner is not None
        assert runner.transaction_state == "committed"
        assert runner.draft_resume["basic"]["summary"] == ("聚焦复杂交互与工程质量。")
        assert (
            runner.draft_resume["sections"][0]["items"][0]["description"]
            == "面向结构化简历编辑与预览工作流。"
        )
        # The rejected batch must never be exposed as a provisional draft.
        assert len(edit_events) == 1
        assert edit_events[0].transaction_state == "provisional"

    asyncio.run(scenario())


def test_corrected_full_batch_commits_after_one_semantic_retry() -> None:
    runner = _runner()

    first_tool, _ = runner._run_local_tool(
        _tool_call(
            "call-invalid",
            [
                {
                    "title": "无效更新",
                    "target": "sections.project.items.missing",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "missing",
                        "patch": {"description": "无效"},
                    },
                },
            ],
        ),
    )
    second_tool, _ = runner._run_local_tool(
        _tool_call(
            "call-corrected",
            [
                _replace_summary("聚焦复杂交互与工程质量。"),
                {
                    "title": "更新项目",
                    "target": "sections.project.items.project-1",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "project-1",
                        "patch": {"description": "构建可验证的 Agent 编辑流程。"},
                    },
                },
            ],
        ),
    )
    runner.finalize_turn()

    assert first_tool.state == "output-error"
    assert second_tool.state == "output-available"
    assert runner.transaction_state == "committed"
    assert runner.draft_resume["basic"]["summary"] == "聚焦复杂交互与工程质量。"
    assert (
        runner.draft_resume["sections"][0]["items"][0]["description"]
        == "构建可验证的 Agent 编辑流程。"
    )


def test_blocking_quality_issue_rejects_batch_and_allows_one_repair() -> None:
    runner = _runner()

    rejected_tool, _ = runner._run_local_tool(
        _tool_call(
            "call-duplicated-fields",
            [
                _replace_summary("聚焦复杂交互与工程质量。"),
                {
                    "title": "更新项目描述",
                    "target": "sections.project.items.project-1",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "project-1",
                        "patch": {
                            "subtitle": "AI 简历编辑器",
                            "description": "ResuMate AI 简历编辑器",
                        },
                    },
                },
            ],
        ),
    )

    assert rejected_tool.state == "output-error"
    assert rejected_tool.output["retryable"] is True
    assert rejected_tool.output["rejectedEdits"][0]["index"] == 2
    assert rejected_tool.output["rejectedEdits"][0]["qualityIssue"]["code"] == (
        "normalized_item_field_was_dropped"
    )
    assert runner.draft_resume["basic"]["summary"] == "原始简介"
    assert "subtitle" not in runner.draft_resume["sections"][0]["items"][0]
    assert runner.draft_resume["sections"][0]["items"][0]["description"] == "原始描述"

    repaired_tool, _ = runner._run_local_tool(
        _tool_call(
            "call-repaired-fields",
            [
                _replace_summary("聚焦复杂交互与工程质量。"),
                {
                    "title": "更新项目描述",
                    "target": "sections.project.items.project-1",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "project-1",
                        "patch": {
                            "subtitle": "AI 简历编辑器",
                            "description": "面向结构化简历编辑与预览工作流。",
                            "highlights": [
                                "实现事务化编辑，避免部分修改进入草稿。",
                                "提供失败诊断，支持模型修复完整批次。",
                            ],
                        },
                    },
                },
            ],
        ),
    )
    runner.finalize_turn()

    assert repaired_tool.state == "output-available"
    assert runner.transaction_state == "committed"
    assert runner.draft_resume["basic"]["summary"] == "聚焦复杂交互与工程质量。"
    assert runner.draft_resume["sections"][0]["items"][0]["subtitle"] == (
        "AI 简历编辑器"
    )
    assert runner.draft_resume["sections"][0]["items"][0]["highlights"] == [
        "实现事务化编辑，避免部分修改进入草稿。",
        "提供失败诊断，支持模型修复完整批次。",
    ]


def test_duplicate_structured_field_values_do_not_false_block_description() -> None:
    runner = _runner()
    item = runner.draft_resume["sections"][0]["items"][0]
    item["subtitle"] = "ResuMate"

    tool, _ = runner._run_local_tool(
        _tool_call(
            "call-equal-structured-fields",
            [
                {
                    "title": "更新项目描述",
                    "target": "sections.project.items.project-1",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "project-1",
                        "patch": {"description": "ResuMate 支持结构化简历编辑。"},
                    },
                },
            ],
        ),
    )

    assert tool.state == "output-available"
    assert runner.semantic_retry_pending is False
    assert item["description"] == "原始描述"
    assert (
        runner.draft_resume["sections"][0]["items"][0]["description"]
        == "ResuMate 支持结构化简历编辑。"
    )


def test_failed_repair_rolls_back_edits_from_the_whole_turn() -> None:
    runner = _runner()

    successful_tool, _ = runner._run_local_tool(
        _tool_call("call-success", [_replace_summary("第一批有效修改")]),
    )
    failed_tool, _ = runner._run_local_tool(
        _tool_call("call-invalid", [_replace_summary("第一批有效修改")]),
    )
    retry_tool, _ = runner._run_local_tool(
        _tool_call("call-invalid-retry", [_replace_summary("第一批有效修改")]),
    )

    assert successful_tool.state == "output-available"
    assert failed_tool.output["retryable"] is True
    assert retry_tool.output["retryExhausted"] is True
    assert runner.transaction_state == "rolled_back"
    assert runner.draft_resume == runner.base_resume
    assert runner.edits == []


def test_unresolved_semantic_error_rolls_back_when_turn_finishes() -> None:
    runner = _runner()
    runner._run_local_tool(
        _tool_call("call-success", [_replace_summary("第一批有效修改")]),
    )
    runner._run_local_tool(
        _tool_call("call-invalid", [_replace_summary("第一批有效修改")]),
    )

    runner.finalize_turn()

    assert runner.transaction_state == "rolled_back"
    assert runner.draft_resume == runner.base_resume
    assert runner.edits == []


def test_blocked_finish_rolls_back_edits_but_keeps_blocked_context() -> None:
    runner = _runner()
    edit_tool, _ = runner._run_local_tool(
        _tool_call("call-success", [_replace_summary("不应提交的修改")]),
    )
    finish_tool, _ = runner._run_local_tool(
        LlmToolCall(
            id="call-finish-blocked",
            name="finish",
            arguments={
                "status": "blocked",
                "reason": "缺少目标岗位。",
                "missing": ["target_role"],
            },
            raw_arguments="{}",
        ),
    )
    runner.finalize_turn()
    message = runner.build_message("message-blocked")

    assert edit_tool.state == "output-available"
    assert finish_tool.state == "output-available"
    assert finish_tool.output["transactionState"] == "rolled_back"
    assert runner.finish_status == "blocked"
    assert runner.finish_reason == "缺少目标岗位。"
    assert runner.finish_missing == ["target_role"]
    assert runner.transaction_state == "rolled_back"
    assert runner.draft_resume == runner.base_resume
    assert runner.edits == []
    assert message.transaction_state == "rolled_back"
    assert message.finish_missing == ["target_role"]
    assert "缺少目标岗位" in message.text
    assert message.edits == []


def test_batch_validation_uses_prior_operations_in_the_same_batch() -> None:
    resume = {"basic": {}, "sections": []}
    edits, rejected = _model_edit_suggestions_with_diagnostics(
        resume,
        [
            {
                "title": "新增项目模块",
                "target": "sections",
                "operation": {
                    "type": "insert_section",
                    "section": {
                        "id": "project",
                        "kind": "project",
                        "layout": "timeline",
                        "items": [],
                    },
                },
            },
            {
                "title": "新增项目条目",
                "target": "sections.project.items",
                "operation": {
                    "type": "insert_item",
                    "sectionId": "project",
                    "item": {"id": "project-1", "title": "ResuMate"},
                },
            },
            {
                "title": "补充项目描述",
                "target": "sections.project.items.project-1",
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"description": "实现事务化 Agent 编辑。"},
                },
            },
        ],
        locale="zh",
    )

    assert rejected == []
    assert [edit.operation["type"] for edit in edits] == [
        "insert_section",
        "insert_item",
        "update_item",
    ]
    assert resume == {"basic": {}, "sections": []}


def test_staged_edits_replay_the_complete_server_operation_sequence() -> None:
    runner = _runner()
    edits = [
        {
            "title": "补充项目描述",
            "target": "sections.project.items.project-1",
            "operation": {
                "type": "update_item",
                "sectionId": "project",
                "itemId": "project-1",
                "patch": {"description": "第一步描述"},
            },
        },
        {
            "title": "补充项目要点",
            "target": "sections.project.items.project-1",
            "operation": {
                "type": "update_item",
                "sectionId": "project",
                "itemId": "project-1",
                "patch": {"highlights": ["第二步要点"]},
            },
        },
    ]

    tool, _ = runner._run_local_tool(_tool_call("call-sequence", edits))

    assert tool.state == "output-available"
    assert [edit.operation for edit in runner.edits] == [
        edit["operation"] for edit in edits
    ]
    item = runner.draft_resume["sections"][0]["items"][0]
    assert item["description"] == "第一步描述"
    assert item["highlights"] == ["第二步要点"]
