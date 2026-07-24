import json

from app.schemas.agent import AgentChatRequest
from app.services.agent.editing.operations import (
    _model_edit_suggestions_with_diagnostics,
)
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmToolCall


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
