import asyncio
import json
from datetime import datetime

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentDraftState,
    AgentResumeEditSuggestion,
)
from app.services.agent.editing.operations import (
    _edit_observations,
    _model_edit_suggestions_with_diagnostics,
)
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.runtime import loop as agent_loop
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.tools.runner import AgentToolRunner
from app.services.agent.tools.structured import draft_diff_summary
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestError,
    LlmToolCall,
)

_CANDIDATE_FACTS = (
    "候选人事实：我关注复杂交互与工程质量。"
    "项目事实：我在 ResuMate 担任产品开发，构建可验证的 Agent 编辑流程，"
    "面向结构化简历编辑与预览工作流，实现事务化编辑以避免部分修改进入草稿，"
    "并提供失败信息以支持模型修复完整批次。"
    "请据此优化个人简介和项目经历。"
)


def _basic(*, headline: str = "", summary: str = "") -> dict:
    return {
        "name": "",
        "headline": headline,
        "phone": "",
        "email": "",
        "location": "",
        "avatar": "",
        "summary": summary,
        "customFields": [],
    }


def _runner() -> AgentToolRunner:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-edit-transaction-runner",
            role="user",
            text=_CANDIDATE_FACTS,
        ),
        locale="zh",
        resume={
            "schemaVersion": 2,
            "basic": _basic(headline="前端工程师", summary="原始简介"),
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "title": "项目经历",
                    "items": [
                        {
                            "id": "project-1",
                            "name": "ResuMate",
                            "role": "",
                            "techStack": [],
                            "period": "",
                            "url": "",
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


def test_same_tool_call_id_and_canonical_arguments_is_idempotent() -> None:
    async def scenario() -> None:
        runner = _runner()
        first_call = LlmToolCall(
            id="call-idempotent-lookup",
            name="resume_lookup",
            arguments={"query": "ResuMate", "includeItems": True},
            raw_arguments='{"query":"ResuMate","includeItems":true}',
        )
        replayed_call = LlmToolCall(
            id="call-idempotent-lookup",
            name="resume_lookup",
            arguments={"includeItems": True, "query": "ResuMate"},
            raw_arguments='{ "includeItems": true, "query": "ResuMate" }',
        )

        first_tool, first_result = await runner.run(
            first_call,
            AgentRuntimeContext(),
        )
        replayed_tool, replayed_result = await runner.run(
            replayed_call,
            AgentRuntimeContext(),
        )

        assert len(runner.tools) == 1
        assert replayed_tool == first_tool
        assert replayed_result == first_result

    asyncio.run(scenario())


def test_idempotent_replay_after_semantic_error_exhausts_repair() -> None:
    async def scenario() -> None:
        runner = _runner()
        invalid_call = _tool_call(
            "call-replayed-semantic-error",
            [_replace_summary("未由用户提供的虚构结论")],
        )

        first_tool, first_result = await runner.run(
            invalid_call,
            AgentRuntimeContext(),
        )
        replayed_tool, replayed_result = await runner.run(
            invalid_call,
            AgentRuntimeContext(),
        )

        assert first_tool.state == "output-error"
        assert first_tool.output["retryable"] is True
        assert replayed_tool == first_tool
        assert replayed_result == first_result
        assert runner.transaction_state == "rolled_back"

    asyncio.run(scenario())


def test_runner_records_completed_tool_timestamps_at_execution_seam() -> None:
    async def scenario() -> None:
        runner = _runner()
        tool_call = LlmToolCall(
            id="call-timed-lookup",
            name="resume_lookup",
            arguments={"query": "ResuMate", "includeItems": True},
            raw_arguments='{"query":"ResuMate","includeItems":true}',
        )

        tool, _ = await runner.run(tool_call, AgentRuntimeContext())

        assert tool.started_at is not None
        assert tool.completed_at is not None
        started_at = datetime.fromisoformat(tool.started_at.replace("Z", "+00:00"))
        completed_at = datetime.fromisoformat(
            tool.completed_at.replace("Z", "+00:00"),
        )
        assert completed_at >= started_at
        assert runner.tools == [tool]

    asyncio.run(scenario())


def test_resume_analysis_uses_current_draft_and_recomputes_target_match() -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-analyze-current-draft",
                role="user",
                text="候选人事实：我有 React 项目经验。请优化简介。",
            ),
            messages=[
                AgentConversationItem(
                    id="assistant-target-react",
                    role="assistant",
                    text="目标已更新。",
                    response={
                        "targetContext": {
                            "kind": "employment",
                            "target": "前端工程师",
                            "mustHaveSkills": ["React"],
                        },
                    },
                ),
            ],
            locale="zh",
            resume={
                "schemaVersion": 2,
                "basic": _basic(headline="前端工程师", summary="原始简介"),
                "sections": [],
            },
        )
        runner = AgentToolRunner(AgentPlanExecutor(request))
        edit_call = _tool_call(
            "call-add-react",
            [_replace_summary("具备 React 项目经验。")],
        )
        analysis_call = LlmToolCall(
            id="call-analyze-current-draft",
            name="resume_analysis",
            arguments={},
            raw_arguments="{}",
        )

        edit_tool, _ = await runner.run(edit_call, AgentRuntimeContext())
        analysis_tool, _ = await runner.run(analysis_call, AgentRuntimeContext())

        assert edit_tool.state == "output-available"
        assert analysis_tool.output["matchedKeywords"] == ["react"]
        assert analysis_tool.output["missingKeywords"] == []
        assert analysis_tool.output["targetFit"]["score"] == 100

    asyncio.run(scenario())


def test_final_message_recomputes_analysis_after_draft_changes() -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-final-current-draft",
                role="user",
                text="候选人事实：我有 React 项目经验。请优化简介。",
            ),
            messages=[
                AgentConversationItem(
                    id="assistant-final-target-react",
                    role="assistant",
                    text="目标已更新。",
                    response={
                        "targetContext": {
                            "kind": "employment",
                            "target": "前端工程师",
                            "mustHaveSkills": ["React"],
                        },
                    },
                ),
            ],
            locale="zh",
            resume={
                "schemaVersion": 2,
                "basic": _basic(headline="前端工程师", summary="原始简介"),
                "sections": [],
            },
        )
        runner = AgentToolRunner(AgentPlanExecutor(request))
        analysis_call = LlmToolCall(
            id="call-analysis-before-edit",
            name="resume_analysis",
            arguments={},
            raw_arguments="{}",
        )

        await runner.run(analysis_call, AgentRuntimeContext())
        assert runner.analysis is not None
        assert runner.analysis.missing_keywords == ["react"]
        await runner.run(
            _tool_call(
                "call-edit-after-analysis",
                [_replace_summary("具备 React 项目经验。")],
            ),
            AgentRuntimeContext(),
        )

        message = runner.build_message("message-current-draft-analysis")

        assert runner.analysis is not None
        assert runner.analysis.matched_keywords == ["react"]
        assert runner.analysis.missing_keywords == []
        assert len(message.suggestions) == 2

    asyncio.run(scenario())


def test_draft_diff_summary_merges_pending_and_current_edits() -> None:
    async def scenario() -> None:
        prior_edit = {
            "id": "edit-prior-headline",
            "title": "更新上一版标题",
            "target": "basic.headline",
            "reason": "聚焦岗位。",
            "replacement": "资深前端工程师",
            "operation": {
                "type": "replace_field",
                "path": "basic.headline",
                "value": "资深前端工程师",
            },
            "status": "executed",
        }
        pending_resume = {
            "schemaVersion": 2,
            "basic": _basic(headline="资深前端工程师", summary="原始简介"),
            "sections": [],
        }
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-merge-pending-diff",
                role="user",
                text=(
                    "候选人事实：我关注复杂交互与工程质量。"
                    "请继续修改上一版草稿，优化个人简介。"
                ),
            ),
            locale="zh",
            resume=pending_resume,
            draftState={
                "id": "draft-pending-merge",
                "status": "pending",
                "resume": pending_resume,
                "editCount": 1,
                "edits": [prior_edit],
                "diffs": [],
            },
        )
        runner = AgentToolRunner(AgentPlanExecutor(request))

        await runner.run(
            _tool_call(
                "call-current-summary",
                [_replace_summary("聚焦复杂交互与工程质量。")],
            ),
            AgentRuntimeContext(),
        )
        diff_tool, _ = await runner.run(
            LlmToolCall(
                id="call-merged-diff",
                name="draft_diff_summary",
                arguments={},
                raw_arguments="{}",
            ),
            AgentRuntimeContext(),
        )

        assert diff_tool.state == "output-available"
        assert diff_tool.output["editCount"] == 2
        assert [edit["id"] for edit in diff_tool.output["edits"]] == [
            "edit-prior-headline",
            runner.edits[0].id,
        ]
        assert [edit["index"] for edit in diff_tool.output["edits"]] == [1, 2]

    asyncio.run(scenario())


def test_draft_diff_summary_does_not_hide_latest_edits() -> None:
    prior_edits = [
        {
            "id": f"edit-prior-{index}",
            "title": f"Prior edit {index}",
            "target": f"sections.projects.items.project-{index}",
            "reason": "Prior pending change.",
            "replacement": f"Prior replacement {index}",
            "operation": {
                "type": "update_item",
                "sectionId": "projects",
                "itemId": f"project-{index}",
                "patch": {"description": f"Prior replacement {index}"},
            },
            "status": "executed",
        }
        for index in range(1, 13)
    ]
    draft_state = AgentDraftState(
        id="draft-many-edits",
        status="pending",
        resume={},
        editCount=len(prior_edits),
        edits=prior_edits,
        diffs=[],
    )
    latest = AgentResumeEditSuggestion(
        id="edit-current-latest",
        title="Latest summary edit",
        target="basic.summary",
        reason="Current request.",
        replacement="Latest summary",
        operation={
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Latest summary",
        },
        status="executed",
    )

    summary = draft_diff_summary(draft_state, [latest])

    assert summary["editCount"] == 13
    assert len(summary["edits"]) == 13
    assert summary["edits"][-1]["id"] == "edit-current-latest"
    assert summary["referenceMap"][-1]["editId"] == "edit-current-latest"


def test_reused_tool_call_id_with_different_arguments_rolls_back() -> None:
    async def scenario() -> None:
        runner = _runner()
        first_call = _tool_call(
            "call-conflicting-edit",
            [_replace_summary("聚焦复杂交互与工程质量。")],
        )
        conflicting_call = _tool_call(
            "call-conflicting-edit",
            [_replace_summary("冲突重放不应被应用。")],
        )

        first_tool, _ = await runner.run(first_call, AgentRuntimeContext())
        assert first_tool.state == "output-available"
        assert runner.draft_resume["basic"]["summary"] == ("聚焦复杂交互与工程质量。")

        with pytest.raises(LlmRequestError, match="reused a tool call id"):
            await runner.run(conflicting_call, AgentRuntimeContext())

        assert runner.transaction_state == "rolled_back"
        assert runner.draft_resume["basic"]["summary"] == "原始简介"
        assert runner.edits == []

    asyncio.run(scenario())


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


def test_same_target_edits_keep_sequential_diffs_by_edit_id() -> None:
    runner = _runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "call-sequential-summary-edits",
            [
                _replace_summary("聚焦复杂交互与工程质量。"),
                _replace_summary("关注复杂交互与工程质量。"),
            ],
        ),
    )

    assert tool.state == "output-available"
    observations = tool.output["observations"]
    assert [item["editId"] for item in observations] == [
        runner.edits[0].id,
        runner.edits[1].id,
    ]
    assert observations[0]["before"] == "原始简介"
    assert observations[0]["after"] == "聚焦复杂交互与工程质量。"
    assert observations[1]["before"] == "聚焦复杂交互与工程质量。"
    assert observations[1]["after"] == "关注复杂交互与工程质量。"
    assert runner.edits[0].diffs[0]["operationId"] == runner.edits[0].id
    assert runner.edits[0].diffs[0]["before"] == "原始简介"
    assert runner.edits[0].diffs[0]["after"] == "聚焦复杂交互与工程质量。"
    assert runner.edits[1].diffs[0]["before"] == "聚焦复杂交互与工程质量。"
    assert runner.edits[1].diffs[0]["after"] == "关注复杂交互与工程质量。"


def test_update_item_records_one_canonical_diff_per_changed_field() -> None:
    runner = _runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "call-field-level-project-diffs",
            [
                {
                    "title": "更新项目经历",
                    "target": "model.supplied.target.must.not.control.diff.path",
                    "reason": "让项目经历更具体。",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "project-1",
                        "patch": {
                            "name": "ResuMate",
                            "description": "面向结构化简历编辑与预览工作流。",
                            "highlights": [
                                "实现事务化编辑以避免部分修改进入草稿。",
                                "提供失败信息以支持模型修复完整批次。",
                            ],
                        },
                    },
                },
            ],
        ),
    )

    assert tool.state == "output-available"
    edit = runner.edits[0]
    assert [diff["path"] for diff in edit.diffs] == [
        "sections.project.items.project-1.description",
        "sections.project.items.project-1.highlights",
    ]
    assert all(diff["operationId"] == edit.id for diff in edit.diffs)
    assert all(diff["sectionId"] == "project" for diff in edit.diffs)
    assert all(diff["itemId"] == "project-1" for diff in edit.diffs)
    assert [diff["label"] for diff in edit.diffs] == ["项目描述", "项目亮点"]
    assert edit.diffs[0]["before"] == "原始描述"
    assert edit.diffs[0]["after"] == "面向结构化简历编辑与预览工作流。"
    assert edit.diffs[1]["before"] == ["原始要点"]
    assert edit.diffs[1]["after"] == [
        "实现事务化编辑以避免部分修改进入草稿。",
        "提供失败信息以支持模型修复完整批次。",
    ]
    summary = draft_diff_summary(None, [edit])
    assert [diff["path"] for diff in summary["diffs"]] == [
        "sections.project.items.project-1.description",
        "sections.project.items.project-1.highlights",
    ]


def test_update_section_diff_targets_only_the_canonical_title_field() -> None:
    runner = _runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "call-section-title-diff",
            [
                {
                    "title": "更新项目标题",
                    "target": "untrusted.section.target",
                    "reason": "让标题更清晰。",
                    "operation": {
                        "type": "update_section",
                        "sectionId": "project",
                        "patch": {"title": "核心项目"},
                    },
                },
            ],
        ),
    )

    assert tool.state == "output-available"
    edit = runner.edits[0]
    assert edit.diffs == [
        {
            "id": f"agent-diff-{edit.id}-title",
            "operationId": edit.id,
            "path": "sections.project.title",
            "kind": "modified",
            "label": "模块标题",
            "sectionId": "project",
            "before": "项目经历",
            "after": "核心项目",
        },
    ]


def test_replace_field_diff_uses_operation_path_instead_of_model_target() -> None:
    runner = _runner()
    edit_entry = _replace_summary("聚焦复杂交互与工程质量。")
    edit_entry["target"] = "untrusted.basic.target"

    tool, _ = runner._run_local_tool(
        _tool_call("call-canonical-replace-field-diff", [edit_entry]),
    )

    assert tool.state == "output-available"
    edit = runner.edits[0]
    assert len(edit.diffs) == 1
    assert edit.diffs[0]["path"] == "basic.summary"
    assert edit.diffs[0]["before"] == "原始简介"
    assert edit.diffs[0]["after"] == "聚焦复杂交互与工程质量。"


def test_insert_item_keeps_one_item_level_structural_diff() -> None:
    runner = _runner()
    inserted_item = {
        "id": "project-2",
        "name": "Agent 编辑流程",
        "role": "产品开发",
        "techStack": [],
        "period": "",
        "url": "",
        "description": "面向结构化简历编辑与预览工作流。",
        "highlights": ["实现事务化编辑以避免部分修改进入草稿。"],
    }

    tool, _ = runner._run_local_tool(
        _tool_call(
            "call-item-level-insert-diff",
            [
                {
                    "title": "新增项目",
                    "target": "untrusted.insert.target",
                    "reason": "补充用户提供的项目事实。",
                    "operation": {
                        "type": "insert_item",
                        "sectionId": "project",
                        "item": inserted_item,
                    },
                },
            ],
        ),
    )

    assert tool.state == "output-available"
    edit = runner.edits[0]
    assert edit.diffs == [
        {
            "id": f"agent-diff-{edit.id}",
            "operationId": edit.id,
            "path": "sections.project.items.project-2",
            "kind": "added",
            "label": "新增项目",
            "sectionId": "project",
            "itemId": "project-2",
            "before": None,
            "after": inserted_item,
        },
    ]


def test_persisted_edit_diff_keeps_complete_values_beyond_model_limits() -> None:
    before_description = "A" * 300
    after_description = "B" * 320
    before_highlights = [f"before-{index}" for index in range(7)]
    after_highlights = [f"after-{index}" for index in range(8)]
    resume = {
        "basic": {},
        "sections": [
            {
                "id": "project",
                "kind": "project",
                "title": "项目经历",
                "items": [
                    {
                        "id": "project-1",
                        "name": "ResuMate",
                        "role": "",
                        "techStack": [],
                        "period": "",
                        "url": "",
                        "description": before_description,
                        "highlights": before_highlights,
                    },
                ],
            },
        ],
    }
    edit = AgentResumeEditSuggestion(
        id="edit-complete-project-diff",
        title="Update project",
        target="sections.project.items.project-1",
        reason="Keep the review payload complete.",
        operation={
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {
                "description": after_description,
                "highlights": after_highlights,
            },
        },
        status="executed",
    )

    observations, diffs_by_edit = _edit_observations(resume, [edit], locale="zh")
    diffs = diffs_by_edit[0]

    assert observations[0]["after"]["description"].endswith("...")
    assert len(observations[0]["after"]["highlights"]) == 6
    assert [diff["path"] for diff in diffs] == [
        "sections.project.items.project-1.description",
        "sections.project.items.project-1.highlights",
    ]
    assert diffs[0]["before"] == before_description
    assert diffs[0]["after"] == after_description
    assert diffs[1]["before"] == before_highlights
    assert diffs[1]["after"] == after_highlights


def test_structural_deletion_diffs_preserve_stable_neighbors() -> None:
    resume = {
        "basic": {},
        "sections": [
            {
                "id": "education",
                "kind": "education",
                "title": "Education",
                "items": [],
            },
            {
                "id": "experience",
                "kind": "experience",
                "title": "Experience",
                "items": [
                    {
                        "id": "first",
                        "company": "First",
                        "position": "",
                        "location": "",
                        "period": "",
                        "description": "",
                        "highlights": [],
                    },
                    {
                        "id": "second",
                        "company": "Second",
                        "position": "",
                        "location": "",
                        "period": "",
                        "description": "",
                        "highlights": [],
                    },
                ],
            },
        ],
    }
    edits = [
        AgentResumeEditSuggestion(
            id="delete-second-item",
            title="Delete second item",
            target="sections.experience.items.second",
            reason="Preserve the review boundary.",
            operation={
                "type": "delete_item",
                "sectionId": "experience",
                "itemId": "second",
            },
            status="executed",
        ),
        AgentResumeEditSuggestion(
            id="delete-education-section",
            title="Delete education",
            target="sections.education",
            reason="Preserve the review boundary.",
            operation={"type": "delete_section", "sectionId": "education"},
            status="executed",
        ),
    ]

    _, diffs_by_edit = _edit_observations(resume, edits, locale="en")

    assert diffs_by_edit[0][0]["beforePreviousId"] == "first"
    assert "beforeNextId" not in diffs_by_edit[0][0]
    assert "beforePreviousId" not in diffs_by_edit[1][0]
    assert diffs_by_edit[1][0]["beforeNextId"] == "experience"


def test_reorder_section_diffs_mark_minimal_moved_sections() -> None:
    resume = {
        "basic": {},
        "sections": [
            {"id": "education", "kind": "education", "title": "Education", "items": []},
            {
                "id": "experience",
                "kind": "experience",
                "title": "Experience",
                "items": [],
            },
            {"id": "project", "kind": "project", "title": "Projects", "items": []},
        ],
    }
    edit = AgentResumeEditSuggestion(
        id="reorder-sections",
        title="Reorder sections",
        target="sections",
        reason="Prioritize projects.",
        operation={
            "type": "reorder_sections",
            "sectionIds": ["experience", "project", "education"],
        },
        status="executed",
    )

    _, diffs_by_edit = _edit_observations(resume, [edit], locale="en")

    assert [
        {
            "path": diff["path"],
            "sectionId": diff["sectionId"],
            "before": diff["before"],
            "after": diff["after"],
        }
        for diff in diffs_by_edit[0]
    ] == [
        {
            "path": "sections.education",
            "sectionId": "education",
            "before": 0,
            "after": 2,
        },
    ]


def test_reorder_item_diffs_mark_deterministic_minimal_moved_items() -> None:
    resume = {
        "basic": {},
        "sections": [
            {
                "id": "experience",
                "kind": "experience",
                "title": "Experience",
                "items": [
                    {
                        "id": item_id,
                        "company": item_id,
                        "position": "",
                        "location": "",
                        "period": "",
                        "description": "",
                        "highlights": [],
                    }
                    for item_id in ("first", "second", "third", "fourth")
                ],
            },
        ],
    }
    edit = AgentResumeEditSuggestion(
        id="reorder-items",
        title="Reorder experience",
        target="sections.experience.items",
        reason="Prioritize the strongest experience.",
        operation={
            "type": "reorder_items",
            "sectionId": "experience",
            "itemIds": ["second", "fourth", "first", "third"],
        },
        status="executed",
    )

    _, diffs_by_edit = _edit_observations(resume, [edit], locale="en")

    assert [
        {
            "path": diff["path"],
            "itemId": diff["itemId"],
            "before": diff["before"],
            "after": diff["after"],
        }
        for diff in diffs_by_edit[0]
    ] == [
        {
            "path": "sections.experience.items.first",
            "itemId": "first",
            "before": 0,
            "after": 2,
        },
        {
            "path": "sections.experience.items.third",
            "itemId": "third",
            "before": 2,
            "after": 3,
        },
    ]


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
    assert runner.draft_resume == original_resume
    assert runner.semantic_retry_pending is True


def test_edit_plan_rejects_action_that_disagrees_with_operation() -> None:
    runner = _runner()

    tool, _ = runner._run_local_tool(
        _plan_tool_call(
            "call-conflicting-plan-action",
            [
                {
                    "action": "update_item",
                    "target": "basic.summary",
                    "reason": "让简介更聚焦。",
                    "operation": _replace_summary(
                        "聚焦复杂交互与工程质量。",
                    )["operation"],
                },
            ],
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["fullBatchRequired"] is True
    assert runner.plan == []
    assert runner.draft_resume["basic"]["summary"] == "原始简介"


def test_invalid_finish_position_rejects_batch_before_any_tool_executes(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-transaction-finish",
                role="user",
                text="优化个人简介",
            ),
            locale="zh",
            resume={
                "schemaVersion": 2,
                "basic": _basic(headline="前端工程师", summary="原始简介"),
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
        tool_run_count = 0
        original_run = AgentToolRunner.run

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            nonlocal response_count
            response_count += 1
            return LlmAssistantMessage(
                tool_calls=[
                    _tool_call(
                        "call-before-finish",
                        [_replace_summary("不应被应用")],
                    ),
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

        async def counted_run(self, tool_call, runtime):
            nonlocal tool_run_count
            tool_run_count += 1
            return await original_run(self, tool_call, runtime)

        monkeypatch.setattr(
            agent_loop,
            "_async_tool_call_response",
            fake_tool_response,
        )
        monkeypatch.setattr(AgentToolRunner, "run", counted_run)

        with pytest.raises(LlmRequestError, match="finish"):
            _ = [
                event
                async for event in agent_loop.async_iter_agent_tool_call_loop(
                    request,
                    config,
                )
            ]

        assert response_count == 1
        assert tool_run_count == 0

    asyncio.run(scenario())


def test_guarded_error_rolls_back_batch_before_finish_can_commit(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-guarded-batch-error",
                role="user",
                text=_CANDIDATE_FACTS,
            ),
            locale="zh",
            resume={
                "schemaVersion": 2,
                "basic": _basic(headline="前端工程师", summary="原始简介"),
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "title": "项目经历",
                        "items": [
                            {
                                "id": "project-1",
                                "name": "ResuMate",
                                "role": "",
                                "techStack": [],
                                "period": "",
                                "url": "",
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
        delete_arguments = {
            "edits": [
                {
                    "title": "删除项目",
                    "target": "sections.project.items.project-1",
                    "reason": "未经用户授权的删除。",
                    "operation": {
                        "type": "delete_item",
                        "sectionId": "project",
                        "itemId": "project-1",
                    },
                },
            ],
        }

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            return LlmAssistantMessage(
                tool_calls=[
                    _tool_call(
                        "call-valid-prefix",
                        [_replace_summary("聚焦复杂交互与工程质量。")],
                    ),
                    LlmToolCall(
                        id="call-guarded-delete",
                        name="edit_execute",
                        arguments=delete_arguments,
                        raw_arguments=json.dumps(
                            delete_arguments,
                            ensure_ascii=False,
                        ),
                    ),
                    LlmToolCall(
                        id="call-finish-guarded-batch",
                        name="finish",
                        arguments={"status": "ready", "reason": "修改已完成。"},
                        raw_arguments=('{"status":"ready","reason":"修改已完成。"}'),
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

        assert runner is not None
        assert [tool.state for tool in runner.tools] == [
            "output-available",
            "output-error",
        ]
        assert runner.finish_status == ""
        assert runner.transaction_state == "rolled_back"
        assert runner.draft_resume["basic"]["summary"] == "原始简介"
        assert runner.edits == []

    asyncio.run(scenario())


def test_quality_rejection_defers_same_response_finish_for_one_repair(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-transaction-quality",
                role="user",
                text=_CANDIDATE_FACTS,
            ),
            locale="zh",
            resume={
                "schemaVersion": 2,
                "basic": _basic(headline="前端工程师", summary="原始简介"),
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "title": "项目经历",
                        "items": [
                            {
                                "id": "project-1",
                                "name": "ResuMate",
                                "role": "",
                                "techStack": [],
                                "period": "",
                                "url": "",
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
                                            "role": "产品开发",
                                            "description": "ResuMate 产品开发",
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
                                        "role": "产品开发",
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


def test_progressive_distinct_semantic_errors_can_each_be_repaired(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="turn-progressive-semantic-repairs",
                role="user",
                text=_CANDIDATE_FACTS,
            ),
            locale="zh",
            resume={
                "schemaVersion": 2,
                "basic": _basic(headline="前端工程师", summary="原始简介"),
                "sections": [
                    {
                        "id": "project",
                        "kind": "project",
                        "title": "项目经历",
                        "items": [
                            {
                                "id": "project-1",
                                "name": "ResuMate",
                                "role": "",
                                "techStack": [],
                                "period": "",
                                "url": "",
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
        summary_edit = _replace_summary("聚焦复杂交互与工程质量。")
        unsupported_project_edit = {
            "title": "更新项目职责",
            "target": "sections.project.items.project-1",
            "reason": "让项目职责更具体。",
            "operation": {
                "type": "update_item",
                "sectionId": "project",
                "itemId": "project-1",
                "patch": {
                    "role": "前端开发",
                    "description": "面向结构化简历编辑与预览工作流。",
                },
            },
        }
        repaired_project_edit = {
            **unsupported_project_edit,
            "operation": {
                **unsupported_project_edit["operation"],
                "patch": {
                    "role": "产品开发",
                    "description": "面向结构化简历编辑与预览工作流。",
                },
            },
        }
        responses = [
            LlmAssistantMessage(
                tool_calls=[
                    _plan_tool_call(
                        "call-plan-out-of-scope",
                        [
                            {
                                "action": "replace_field",
                                "target": "basic.headline",
                                "reason": "越界修改标题。",
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.headline",
                                    "value": "产品负责人",
                                },
                            },
                        ],
                    ),
                ],
                stop_reason="tool_calls",
            ),
            LlmAssistantMessage(
                tool_calls=[
                    _plan_tool_call(
                        "call-plan-action-mismatch",
                        [
                            {
                                "action": "update_item",
                                "target": summary_edit["target"],
                                "reason": summary_edit["reason"],
                                "operation": summary_edit["operation"],
                            },
                        ],
                    ),
                ],
                stop_reason="tool_calls",
            ),
            LlmAssistantMessage(
                tool_calls=[
                    _plan_tool_call(
                        "call-plan-corrected",
                        [
                            {
                                "action": "replace_field",
                                "target": summary_edit["target"],
                                "reason": summary_edit["reason"],
                                "operation": summary_edit["operation"],
                            },
                            {
                                "action": "update_item",
                                "target": unsupported_project_edit["target"],
                                "reason": unsupported_project_edit["reason"],
                                "operation": unsupported_project_edit["operation"],
                            },
                        ],
                    ),
                ],
                stop_reason="tool_calls",
            ),
            LlmAssistantMessage(
                tool_calls=[
                    _tool_call(
                        "call-execute-unsupported-claim",
                        [summary_edit, unsupported_project_edit],
                    ),
                ],
                stop_reason="tool_calls",
            ),
            LlmAssistantMessage(
                tool_calls=[
                    _tool_call(
                        "call-execute-repaired-claim",
                        [summary_edit, repaired_project_edit],
                    ),
                    LlmToolCall(
                        id="call-finish-progressive-repairs",
                        name="finish",
                        arguments={"status": "ready", "reason": "修改已完成。"},
                        raw_arguments="{}",
                    ),
                ],
                stop_reason="tool_calls",
            ),
        ]
        response_count = 0

        async def fake_tool_response(*_args, **_kwargs) -> LlmAssistantMessage:
            nonlocal response_count
            response = responses[response_count]
            response_count += 1
            return response

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

        assert response_count == 5
        assert runner is not None
        assert [tool.state for tool in runner.tools] == [
            "output-error",
            "output-error",
            "output-available",
            "output-error",
            "output-available",
        ]
        assert runner.tools[0].output["retryable"] is True
        assert runner.tools[1].output["retryable"] is True
        assert runner.tools[3].output["retryable"] is True
        assert runner.transaction_state == "committed"
        assert runner.draft_resume["basic"]["summary"] == ("聚焦复杂交互与工程质量。")
        assert runner.draft_resume["sections"][0]["items"][0]["role"] == ("产品开发")

    asyncio.run(scenario())


def test_runner_rejects_repeated_semantic_state_without_progress() -> None:
    async def scenario() -> None:
        runner = _runner()
        invalid_plan = _plan_tool_call(
            "call-runner-invalid-plan",
            [
                {
                    "action": "update_item",
                    "target": "sections.project.items.missing",
                    "reason": "更新不存在的项目。",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "missing",
                        "patch": {"description": "不会被应用"},
                    },
                },
            ],
        )
        valid_plan = _plan_tool_call(
            "call-runner-valid-plan",
            [
                {
                    "action": "replace_field",
                    "target": "basic.summary",
                    "reason": "让简介更聚焦。",
                    "operation": _replace_summary(
                        "聚焦复杂交互与工程质量。",
                    )["operation"],
                },
            ],
        )
        unsupported_edits = [
            {
                "title": "添加未经证实的项目职责",
                "target": "sections.project.items.project-1",
                "reason": "让项目职责更具体。",
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"role": "前端开发"},
                },
            },
        ]
        unsupported_edit = _tool_call(
            "call-runner-unsupported-edit",
            unsupported_edits,
        )
        repeated_unsupported_edit = _tool_call(
            "call-runner-unsupported-edit-repeated",
            unsupported_edits,
        )
        distinct_invalid_edit = _tool_call(
            "call-runner-distinct-invalid-edit",
            [
                {
                    "title": "更新不存在的项目",
                    "target": "sections.project.items.missing",
                    "reason": "更新项目描述。",
                    "operation": {
                        "type": "update_item",
                        "sectionId": "project",
                        "itemId": "missing",
                        "patch": {"description": "不会被应用"},
                    },
                },
            ],
        )

        first_error, _ = await runner.run(invalid_plan, AgentRuntimeContext())
        repaired_plan, _ = await runner.run(valid_plan, AgentRuntimeContext())
        second_error, _ = await runner.run(
            unsupported_edit,
            AgentRuntimeContext(),
        )
        distinct_error, _ = await runner.run(
            distinct_invalid_edit,
            AgentRuntimeContext(),
        )
        repeated_error, _ = await runner.run(
            repeated_unsupported_edit,
            AgentRuntimeContext(),
        )

        assert first_error.output["retryable"] is True
        assert repaired_plan.state == "output-available"
        assert second_error.output["retryable"] is True
        assert distinct_error.output["retryable"] is True
        assert repeated_error.output["retryable"] is False
        assert repeated_error.output["retryExhausted"] is True
        assert repeated_error.output["sameBatch"] is False
        assert runner.transaction_state == "rolled_back"
        assert runner.draft_resume == runner.base_resume
        assert runner.edits == []

    asyncio.run(scenario())


def test_unchanged_successful_plan_does_not_refresh_semantic_repair() -> None:
    async def scenario() -> None:
        runner = _runner()
        valid_steps = [
            {
                "action": "replace_field",
                "target": "basic.summary",
                "reason": "让简介更聚焦。",
                "operation": _replace_summary(
                    "聚焦复杂交互与工程质量。",
                )["operation"],
            },
        ]
        invalid_steps = [
            {
                "action": "update_item",
                "target": "sections.project.items.missing",
                "reason": "更新不存在的项目。",
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "missing",
                    "patch": {"description": "不会被应用"},
                },
            },
        ]

        await runner.run(
            _plan_tool_call("call-initial-valid-plan", valid_steps),
            AgentRuntimeContext(),
        )
        first_error, _ = await runner.run(
            _plan_tool_call("call-invalid-plan-after-success", invalid_steps),
            AgentRuntimeContext(),
        )
        unchanged_plan, _ = await runner.run(
            _plan_tool_call("call-unchanged-valid-plan", valid_steps),
            AgentRuntimeContext(),
        )
        repeated_error, _ = await runner.run(
            _plan_tool_call("call-repeated-invalid-plan", invalid_steps),
            AgentRuntimeContext(),
        )

        assert first_error.output["retryable"] is True
        assert unchanged_plan.state == "output-available"
        assert repeated_error.output["retryable"] is False
        assert repeated_error.output["retryExhausted"] is True
        assert repeated_error.output["sameBatch"] is True
        assert runner.transaction_state == "rolled_back"

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
                            "role": "产品开发",
                            "description": "ResuMate 产品开发",
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
    assert runner.draft_resume["sections"][0]["items"][0]["role"] == ""
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
                            "role": "产品开发",
                            "description": "面向结构化简历编辑与预览工作流。",
                            "highlights": [
                                "实现事务化编辑，避免部分修改进入草稿。",
                                "提供失败信息，支持模型修复完整批次。",
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
    assert runner.draft_resume["sections"][0]["items"][0]["role"] == "产品开发"
    assert runner.draft_resume["sections"][0]["items"][0]["highlights"] == [
        "实现事务化编辑，避免部分修改进入草稿。",
        "提供失败信息，支持模型修复完整批次。",
    ]


def test_duplicate_structured_field_values_do_not_false_block_description() -> None:
    runner = _runner()
    item = runner.draft_resume["sections"][0]["items"][0]
    item["role"] = "ResuMate"

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
        _tool_call("call-success", [_replace_summary("精简的原始简介")]),
    )
    failed_tool, _ = runner._run_local_tool(
        _tool_call("call-invalid", [_replace_summary("精简的原始简介")]),
    )
    retry_tool, _ = runner._run_local_tool(
        _tool_call("call-invalid-retry", [_replace_summary("精简的原始简介")]),
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
        _tool_call("call-success", [_replace_summary("精简的原始简介")]),
    )
    runner._run_local_tool(
        _tool_call("call-invalid", [_replace_summary("精简的原始简介")]),
    )

    runner.finalize_turn()

    assert runner.transaction_state == "rolled_back"
    assert runner.draft_resume == runner.base_resume
    assert runner.edits == []


def test_blocked_finish_rolls_back_edits_but_keeps_blocked_context() -> None:
    runner = _runner()
    edit_tool, _ = runner._run_local_tool(
        _tool_call("call-success", [_replace_summary("精简的原始简介")]),
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
    resume = {"schemaVersion": 2, "basic": _basic(), "sections": []}
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
                        "title": "项目经历",
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
                    "item": {"id": "project-1", "name": "ResuMate"},
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
    assert resume == {"schemaVersion": 2, "basic": _basic(), "sections": []}


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
                "patch": {"description": "面向结构化简历编辑与预览工作流"},
            },
        },
        {
            "title": "补充项目要点",
            "target": "sections.project.items.project-1",
            "operation": {
                "type": "update_item",
                "sectionId": "project",
                "itemId": "project-1",
                "patch": {"highlights": ["实现事务化编辑，避免部分修改进入草稿"]},
            },
        },
    ]

    tool, _ = runner._run_local_tool(_tool_call("call-sequence", edits))

    assert tool.state == "output-available"
    assert [edit.operation for edit in runner.edits] == [
        edit["operation"] for edit in edits
    ]
    item = runner.draft_resume["sections"][0]["items"][0]
    assert item["description"] == "面向结构化简历编辑与预览工作流"
    assert item["highlights"] == ["实现事务化编辑，避免部分修改进入草稿"]
