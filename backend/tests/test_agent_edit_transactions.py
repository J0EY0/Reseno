import asyncio
import json
from copy import deepcopy
from datetime import datetime

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentResumeEditSuggestion,
)
from app.services.agent.draft import DraftEditEngine
from app.services.agent.editing.operations import _edit_observations
from app.services.agent.environment import ResumeToolEnvironment
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.llm import LlmRequestError, LlmToolCall

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


def _resume() -> dict:
    return {
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
    }


def _request(
    prompt: str = _CANDIDATE_FACTS,
    *,
    resume: dict | None = None,
    messages: list[AgentConversationItem] | None = None,
    draft_state: dict | None = None,
) -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="turn-edit-transaction",
            role="user",
            text=prompt,
        ),
        messages=messages or [],
        locale="zh",
        resume=deepcopy(resume or _resume()),
        draftState=deepcopy(draft_state),
    )


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
        "evidenceRefs": ["prompt:current"],
        "operation": {
            "type": "replace_field",
            "path": "basic.summary",
            "value": value,
        },
    }


def _missing_item_edit() -> dict:
    return {
        "title": "更新不存在的项目",
        "target": "sections.project.items.missing",
        "reason": "更新项目描述。",
        "evidenceRefs": ["prompt:current"],
        "operation": {
            "type": "update_item",
            "sectionId": "project",
            "itemId": "missing",
            "patch": {"description": "不会被应用"},
        },
    }


def test_environment_replays_canonical_read_call_idempotently() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request())
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

        first = await environment.invoke(first_call, AgentRuntimeContext())
        replayed = await environment.invoke(replayed_call, AgentRuntimeContext())
        result = environment.close(completed=True)

        assert len(result.tools) == 1
        assert replayed.invocation == first.invocation
        assert replayed.observation == first.observation
        assert replayed.edits_changed is False

    asyncio.run(scenario())


def test_environment_records_completed_tool_timestamps() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request())
        effect = await environment.invoke(
            LlmToolCall(
                id="call-timed-lookup",
                name="resume_lookup",
                arguments={"query": "ResuMate", "includeItems": True},
                raw_arguments='{"query":"ResuMate","includeItems":true}',
            ),
            AgentRuntimeContext(),
        )

        tool = effect.invocation
        assert tool.started_at is not None
        assert tool.completed_at is not None
        started_at = datetime.fromisoformat(tool.started_at.replace("Z", "+00:00"))
        completed_at = datetime.fromisoformat(
            tool.completed_at.replace("Z", "+00:00"),
        )
        result = environment.close(completed=True)

        assert completed_at >= started_at
        assert result.tools == (tool,)

    asyncio.run(scenario())


def test_reused_tool_call_id_with_different_arguments_rolls_back() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request())
        first = await environment.invoke(
            _tool_call(
                "call-conflicting-edit",
                [_replace_summary("聚焦复杂交互与工程质量。")],
            ),
            AgentRuntimeContext(),
        )

        assert first.invocation.state == "output-available"
        assert first.transaction_state == "provisional"
        assert len(first.edits) == 1

        with pytest.raises(LlmRequestError, match="reused a tool call id"):
            await environment.invoke(
                _tool_call(
                    "call-conflicting-edit",
                    [_replace_summary("冲突重放不应被应用。")],
                ),
                AgentRuntimeContext(),
            )

        result = environment.close(completed=False)

        assert result.transaction_state == "rolled_back"
        assert result.edits == ()

    asyncio.run(scenario())


def test_replayed_rejected_edit_remains_recoverable() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request())
        invalid_call = _tool_call(
            "call-replayed-semantic-error",
            [_missing_item_edit()],
        )

        first = await environment.invoke(invalid_call, AgentRuntimeContext())
        replayed = await environment.invoke(invalid_call, AgentRuntimeContext())
        repaired = await environment.invoke(
            _tool_call(
                "call-repaired-edit",
                [_replace_summary("聚焦复杂交互与工程质量。")],
            ),
            AgentRuntimeContext(),
        )

        assert first.invocation.state == "output-error"
        assert first.invocation.output["retryable"] is True
        assert replayed.invocation == first.invocation
        assert replayed.observation == first.observation
        assert not hasattr(replayed, "terminal")
        assert repaired.invocation.state == "output-available"

    asyncio.run(scenario())


def test_edit_batch_is_atomic_when_one_operation_is_invalid() -> None:
    engine = DraftEditEngine.open(_request())
    original_resume = engine.draft_resume

    batch = engine.execute(
        [
            _replace_summary("聚焦复杂交互与工程质量。"),
            _missing_item_edit(),
        ],
    )

    assert batch.accepted is False
    assert batch.observation["retryable"] is True
    assert engine.draft_resume == original_resume
    assert engine.edits == ()
    assert engine.retry_pending is True
    assert engine.revision == 0


def test_exact_noop_does_not_reject_another_valid_edit_in_the_batch() -> None:
    engine = DraftEditEngine.open(_request())

    batch = engine.execute(
        [
            _replace_summary("原始简介"),
            {
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {
                        "description": "面向结构化简历编辑与预览工作流。",
                    },
                },
            },
        ],
    )

    assert batch.accepted is True
    assert batch.observation["editCount"] == 1
    assert batch.draft_resume["basic"]["summary"] == "原始简介"
    assert batch.draft_resume["sections"][0]["items"][0]["description"] == (
        "面向结构化简历编辑与预览工作流。"
    )
    assert engine.retry_pending is False


def test_equivalent_highlight_representation_is_a_noop() -> None:
    resume = _resume()
    original_highlights = [
        "<ul><li>修复问题</li><li>优化性能</li></ul>",
    ]
    resume["sections"][0]["items"][0]["highlights"] = original_highlights
    engine = DraftEditEngine.open(_request(resume=resume))

    batch = engine.execute(
        [
            {
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"highlights": ["修复问题", "优化性能"]},
                },
            },
        ],
    )

    assert batch.accepted is False
    assert batch.observation["editCount"] == 0
    assert batch.draft_resume["sections"][0]["items"][0]["highlights"] == (
        original_highlights
    )
    assert batch.edits == ()
    assert engine.revision == 0


def test_tiptap_list_paragraph_wrappers_do_not_create_a_highlight_edit() -> None:
    resume = _resume()
    original_highlights = [
        "<ul>\n<li><p>修复问题</p></li>\n<li><p>优化性能</p></li>\n</ul>",
    ]
    resume["sections"][0]["items"][0]["highlights"] = original_highlights
    engine = DraftEditEngine.open(_request(resume=resume))

    batch = engine.execute(
        [
            {
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"highlights": ["修复问题", "优化性能"]},
                },
            },
        ],
    )

    assert batch.accepted is False
    assert batch.draft_resume["sections"][0]["items"][0]["highlights"] == (
        original_highlights
    )
    assert batch.edits == ()


def test_simple_list_inter_tag_whitespace_is_a_noop() -> None:
    resume = _resume()
    original_content = "<ul><li>React</li>\n<li>TypeScript</li></ul>"
    resume["sections"].append(
        {
            "id": "skills",
            "kind": "simple_list",
            "title": "技能",
            "items": [{"id": "skills-1", "content": original_content}],
        },
    )
    engine = DraftEditEngine.open(_request(resume=resume))

    batch = engine.execute(
        [
            {
                "operation": {
                    "type": "update_item",
                    "sectionId": "skills",
                    "itemId": "skills-1",
                    "patch": {
                        "content": "<ul><li>React</li><li>TypeScript</li></ul>",
                    },
                },
            },
        ],
    )

    assert batch.accepted is False
    assert batch.draft_resume["sections"][1]["items"][0]["content"] == (
        original_content
    )
    assert batch.edits == ()


def test_changed_highlights_keep_the_editor_html_shape_and_escape_plain_text() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"] = [
        "<ul><li>旧要点</li></ul>",
    ]
    engine = DraftEditEngine.open(_request(resume=resume))

    batch = engine.execute(
        [
            {
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"highlights": ["React < Vue", "优化性能"]},
                },
            },
        ],
    )

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["highlights"] == [
        "<ul><li>React &lt; Vue</li><li>优化性能</li></ul>",
    ]


@pytest.mark.parametrize(
    "formatted",
    [
        "<ul><li><strong>修复问题</strong></li></ul>",
        "<ol><li>修复问题</li></ol>",
    ],
)
def test_highlight_format_change_is_not_a_noop(formatted: str) -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"] = [
        "<ul><li>修复问题</li></ul>",
    ]
    engine = DraftEditEngine.open(_request(resume=resume))

    batch = engine.execute(
        [
            {
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"highlights": [formatted]},
                },
            },
        ],
    )

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["highlights"] == [
        formatted,
    ]
    assert len(batch.edits[0].diffs) == 1


def test_corrected_full_batch_commits_after_rejection() -> None:
    engine = DraftEditEngine.open(_request())
    rejected = engine.execute([_missing_item_edit()])
    corrected = engine.execute(
        [
            _replace_summary("聚焦复杂交互与工程质量。"),
            {
                "title": "更新项目",
                "target": "sections.project.items.project-1",
                "reason": "使用候选人提供的项目事实。",
                "evidenceRefs": [
                    "resume:item:project:project-1",
                    "prompt:current",
                ],
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {
                        "description": "面向结构化简历编辑与预览工作流。",
                    },
                },
            },
        ],
    )
    turn = engine.finalize(completed=True)

    assert rejected.accepted is False
    assert corrected.accepted is True
    assert turn.transaction_state == "committed"
    assert turn.draft_resume is not None
    assert turn.draft_resume["basic"]["summary"] == "聚焦复杂交互与工程质量。"
    assert turn.draft_resume["sections"][0]["items"][0]["description"] == (
        "面向结构化简历编辑与预览工作流。"
    )


def test_rejected_batch_preserves_earlier_staged_edits() -> None:
    engine = DraftEditEngine.open(_request())
    summary_edit = _replace_summary("聚焦复杂交互与工程质量。")
    project_edit = {
        "title": "更新项目",
        "target": "sections.project.items.project-1",
        "reason": "使用候选人提供的项目事实。",
        "evidenceRefs": [
            "resume:item:project:project-1",
            "prompt:current",
        ],
        "operation": {
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {
                "description": "面向结构化简历编辑与预览工作流。",
            },
        },
    }

    first = engine.execute([summary_edit])
    rejected = engine.execute([_missing_item_edit()])
    retried = engine.execute([project_edit])
    turn = engine.finalize(completed=True)

    assert first.accepted is True
    assert rejected.accepted is False
    assert rejected.draft_resume["basic"]["summary"] == ("聚焦复杂交互与工程质量。")
    assert rejected.edits == first.edits
    assert rejected.revision == first.revision == 1
    assert retried.accepted is True
    assert retried.revision == 2
    assert turn.transaction_state == "committed"
    assert turn.draft_resume is not None
    assert turn.draft_resume["basic"]["summary"] == ("聚焦复杂交互与工程质量。")
    assert turn.draft_resume["sections"][0]["items"][0]["description"] == (
        "面向结构化简历编辑与预览工作流。"
    )
    assert [edit.operation["type"] for edit in turn.edits if edit.operation] == [
        "replace_field",
        "update_item",
    ]


def test_rejected_followup_preserves_accepted_draft_on_completion() -> None:
    engine = DraftEditEngine.open(_request())
    accepted = engine.execute(
        [_replace_summary("聚焦复杂交互与工程质量。")],
    )
    rejected = engine.execute([_missing_item_edit()])

    turn = engine.finalize(completed=True)

    assert accepted.accepted is True
    assert rejected.accepted is False
    assert rejected.edits == accepted.edits
    assert turn.transaction_state == "committed"
    assert turn.draft_resume is not None
    assert turn.draft_resume["basic"]["summary"] == "聚焦复杂交互与工程质量。"
    assert turn.edits == accepted.edits


def test_rejected_only_turn_has_no_pending_draft() -> None:
    engine = DraftEditEngine.open(_request())
    rejected = engine.execute([_missing_item_edit()])

    turn = engine.finalize(completed=True)

    assert rejected.accepted is False
    assert turn.transaction_state == "rolled_back"
    assert turn.draft_resume is None
    assert turn.edits == ()


def test_aborted_turn_rolls_back_all_staged_edits() -> None:
    engine = DraftEditEngine.open(_request())
    accepted = engine.execute(
        [_replace_summary("聚焦复杂交互与工程质量。")],
    )

    turn = engine.finalize(completed=False)

    assert accepted.accepted is True
    assert turn.transaction_state == "rolled_back"
    assert turn.draft_resume is None
    assert turn.edits == ()
    assert engine.draft_resume == engine.base_resume


def test_same_target_edits_keep_sequential_diffs_by_edit_id() -> None:
    engine = DraftEditEngine.open(_request())

    batch = engine.execute(
        [
            _replace_summary("聚焦复杂交互与工程质量。"),
            _replace_summary("关注复杂交互与工程质量。"),
        ],
    )

    assert batch.accepted is True
    observations = batch.observation["observations"]
    assert [item["editId"] for item in observations] == [
        batch.edits[0].id,
        batch.edits[1].id,
    ]
    assert observations[0]["before"] == "原始简介"
    assert observations[0]["after"] == "聚焦复杂交互与工程质量。"
    assert observations[1]["before"] == "聚焦复杂交互与工程质量。"
    assert observations[1]["after"] == "关注复杂交互与工程质量。"
    assert batch.edits[0].diffs[0]["operationId"] == batch.edits[0].id
    assert batch.edits[1].diffs[0]["operationId"] == batch.edits[1].id


def test_update_item_records_canonical_field_diffs() -> None:
    engine = DraftEditEngine.open(_request())

    batch = engine.execute(
        [
            {
                "title": "更新项目经历",
                "target": "model.supplied.target.must.not.control.diff.path",
                "reason": "让项目经历更具体。",
                "evidenceRefs": [
                    "resume:item:project:project-1",
                    "prompt:current",
                ],
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
    )

    assert batch.accepted is True
    edit = batch.edits[0]
    assert [diff["path"] for diff in edit.diffs] == [
        "sections.project.items.project-1.description",
        "sections.project.items.project-1.highlights",
    ]
    assert all(diff["operationId"] == edit.id for diff in edit.diffs)
    assert [diff["label"] for diff in edit.diffs] == ["项目描述", "项目亮点"]
    assert edit.diffs[0]["before"] == "原始描述"
    assert edit.diffs[0]["after"] == "面向结构化简历编辑与预览工作流。"
    assert edit.diffs[1]["before"] == ["原始要点"]
    assert edit.diffs[1]["after"] == [
        "实现事务化编辑以避免部分修改进入草稿。",
        "提供失败信息以支持模型修复完整批次。",
    ]


def test_insert_item_keeps_one_item_level_structural_diff() -> None:
    engine = DraftEditEngine.open(
        _request(
            "项目事实：我在 Agent 编辑流程担任产品开发，面向结构化简历编辑与"
            "预览工作流，实现事务化编辑以避免部分修改进入草稿。请新增到项目经历。",
        ),
    )
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

    batch = engine.execute(
        [
            {
                "title": "新增项目",
                "target": "untrusted.insert.target",
                "reason": "补充用户提供的项目事实。",
                "evidenceRefs": ["prompt:current"],
                "operation": {
                    "type": "insert_item",
                    "sectionId": "project",
                    "item": inserted_item,
                },
            },
        ],
    )

    assert batch.accepted is True
    edit = batch.edits[0]
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


def test_diff_values_are_not_truncated_at_the_persistence_boundary() -> None:
    before_description = "A" * 300
    after_description = "B" * 320
    before_highlights = [f"before-{index}" for index in range(7)]
    after_highlights = [f"after-{index}" for index in range(8)]
    resume = _resume()
    item = resume["sections"][0]["items"][0]
    item["description"] = before_description
    item["highlights"] = before_highlights
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

    assert observations[0]["after"]["description"] == after_description
    assert observations[0]["after"]["highlights"] == after_highlights
    assert diffs[0]["before"] == before_description
    assert diffs[0]["after"] == after_description
    assert diffs[1]["before"] == before_highlights
    assert diffs[1]["after"] == after_highlights


def test_structural_diffs_preserve_neighbors_and_minimal_reorders() -> None:
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
    delete_edit = AgentResumeEditSuggestion(
        id="delete-fourth",
        title="Delete fourth item",
        target="sections.experience.items.fourth",
        reason="Preserve the review boundary.",
        operation={
            "type": "delete_item",
            "sectionId": "experience",
            "itemId": "fourth",
        },
        status="executed",
    )
    reorder_edit = AgentResumeEditSuggestion(
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

    _, delete_diffs = _edit_observations(resume, [delete_edit], locale="en")
    _, reorder_diffs = _edit_observations(resume, [reorder_edit], locale="en")

    assert delete_diffs[0][0]["beforePreviousId"] == "third"
    assert "beforeNextId" not in delete_diffs[0][0]
    assert [
        (diff["itemId"], diff["before"], diff["after"]) for diff in reorder_diffs[0]
    ] == [("first", 0, 2), ("third", 2, 3)]


def test_batch_validation_uses_prior_operations_and_preserves_sequence() -> None:
    empty_resume = {
        "schemaVersion": 2,
        "basic": _basic(),
        "sections": [],
    }
    engine = DraftEditEngine.open(
        _request(
            "项目事实：我开发 ResuMate，角色：开发者，实现事务化 Agent 编辑。"
            "请新增项目经历模块、项目条目和项目描述。",
            resume=empty_resume,
        ),
    )
    project_item = {
        "id": "project-1",
        "name": "ResuMate",
        "role": "开发者",
        "techStack": [],
        "period": "",
        "url": "",
        "description": "",
        "highlights": [],
    }
    entries = [
        {
            "title": "新增项目模块",
            "target": "sections",
            "evidenceRefs": ["prompt:current"],
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
            "evidenceRefs": ["prompt:current"],
            "operation": {
                "type": "insert_item",
                "sectionId": "project",
                "item": project_item,
            },
        },
        {
            "title": "补充项目描述",
            "target": "sections.project.items.project-1",
            "evidenceRefs": ["prompt:current"],
            "operation": {
                "type": "update_item",
                "sectionId": "project",
                "itemId": "project-1",
                "patch": {"description": "实现事务化 Agent 编辑。"},
            },
        },
    ]

    batch = engine.execute(entries)

    assert batch.accepted is True
    assert [edit.operation for edit in batch.edits] == [
        entry["operation"] for entry in entries
    ]
    assert engine.base_resume == empty_resume
    assert engine.draft_resume["sections"][0]["items"][0]["description"] == (
        "实现事务化 Agent 编辑。"
    )
