import json
from copy import deepcopy

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.policy import (
    AgentCapabilityMode,
    capability_policy_for_request,
    has_explicit_delete_intent,
    has_explicit_reorder_intent,
)
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmToolCall


def _resume() -> dict:
    return {
        "schemaVersion": 2,
        "basic": {
            "name": "候选人",
            "headline": "前端工程师",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "关注复杂交互与工程质量。",
            "customFields": [],
        },
        "sections": [
            {
                "id": "experience",
                "kind": "experience",
                "title": "实习经历",
                "items": [
                    {
                        "id": "tencent",
                        "company": "企业协同产品线",
                        "position": "腾讯前端开发实习生",
                        "location": "深圳",
                        "period": "2024.03 - 2024.06",
                        "description": "参与内部协作平台开发。",
                        "highlights": ["维护业务组件。", "协助定位交互问题。"],
                    },
                    {
                        "id": "alibaba",
                        "company": "阿里巴巴",
                        "position": "开发实习生",
                        "location": "杭州",
                        "period": "2023.07 - 2023.09",
                        "description": "参与运营平台开发。",
                        "highlights": ["维护页面功能。"],
                    },
                ],
            },
            {
                "id": "project",
                "kind": "project",
                "title": "项目经历",
                "items": [
                    {
                        "id": "resumate",
                        "name": "结构化简历平台",
                        "role": "开发者",
                        "techStack": ["ResuMate"],
                        "period": "",
                        "url": "",
                        "description": "结构化简历编辑器。",
                        "highlights": ["实现简历编辑流程。"],
                    },
                    {
                        "id": "other-project",
                        "name": "协作看板",
                        "role": "开发者",
                        "techStack": [],
                        "period": "",
                        "url": "",
                        "description": "团队任务协作工具。",
                        "highlights": ["实现任务维护流程。"],
                    },
                ],
            },
            {
                "id": "skills",
                "kind": "simple_list",
                "title": "技能",
                "items": [
                    {
                        "id": "skills-1",
                        "content": "前端：组件开发；工程：自动化测试",
                    },
                ],
            },
        ],
    }


def _runner(prompt: str) -> AgentToolRunner:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id=f"turn-{abs(hash(prompt))}",
            role="user",
            text=prompt,
        ),
        locale="zh",
        resume=_resume(),
    )
    return AgentToolRunner(AgentPlanExecutor(request))


def _pending_deleted_project_runner() -> tuple[AgentToolRunner, dict]:
    formal_resume = _resume()
    pending_resume = deepcopy(formal_resume)
    deleted_item = pending_resume["sections"][1]["items"].pop(0)
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-restore-deleted-item",
            role="user",
            text="撤回刚才删除的项目。",
        ),
        locale="zh",
        resume=formal_resume,
        draftState={
            "id": "draft-deleted-item",
            "status": "pending",
            "resume": pending_resume,
            "editCount": 1,
            "edits": [
                {
                    "operation": {
                        "type": "delete_item",
                        "sectionId": "project",
                        "itemId": deleted_item["id"],
                    },
                },
            ],
            "diffs": [],
        },
    )
    return AgentToolRunner(AgentPlanExecutor(request)), deleted_item


def _pending_deleted_section_runner() -> tuple[AgentToolRunner, dict]:
    formal_resume = _resume()
    pending_resume = deepcopy(formal_resume)
    deleted_section = pending_resume["sections"].pop(1)
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-restore-deleted-section",
            role="user",
            text="恢复刚才删除的项目模块。",
        ),
        locale="zh",
        resume=formal_resume,
        draftState={
            "id": "draft-deleted-section",
            "status": "pending",
            "resume": pending_resume,
            "editCount": 1,
            "edits": [
                {
                    "operation": {
                        "type": "delete_section",
                        "sectionId": deleted_section["id"],
                    },
                },
            ],
            "diffs": [],
        },
    )
    return AgentToolRunner(AgentPlanExecutor(request)), deleted_section


def _pending_tencent_highlights_runner() -> tuple[AgentToolRunner, list[str]]:
    formal_resume = _resume()
    pending_resume = deepcopy(formal_resume)
    original_highlights = formal_resume["sections"][0]["items"][0]["highlights"]
    pending_highlights = [
        "维护企业协同业务组件。",
        "协助定位复杂交互问题。",
    ]
    pending_resume["sections"][0]["items"][0]["highlights"] = pending_highlights
    prior_edit = _edit(
        {
            "type": "update_item",
            "sectionId": "experience",
            "itemId": "tencent",
            "patch": {"highlights": pending_highlights},
        },
        target="sections.experience.items.tencent",
    )
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-shorten-pending-second-bullet",
            role="user",
            text="保留其他修改，只把刚才第二条 bullet 改短一点。",
        ),
        locale="zh",
        resume=formal_resume,
        draftState={
            "id": "draft-tencent-highlights",
            "status": "pending",
            "resume": pending_resume,
            "editCount": 1,
            "edits": [prior_edit],
            "diffs": [
                {
                    "operationId": "edit-tencent-highlights",
                    "path": "sections.experience.items.tencent.highlights",
                    "before": original_highlights,
                    "after": pending_highlights,
                },
            ],
        },
    )
    return AgentToolRunner(AgentPlanExecutor(request)), pending_highlights


def _tool_call(name: str, arguments: dict) -> LlmToolCall:
    return LlmToolCall(
        id=f"call-{name}",
        name=name,
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _edit(operation: dict, *, target: str) -> dict:
    return {
        "title": "更新内容",
        "target": target,
        "reason": "按用户指定范围整理表达。",
        "operation": operation,
    }


def _tencent_bullet_edit() -> dict:
    return _edit(
        {
            "type": "update_item",
            "sectionId": "experience",
            "itemId": "tencent",
            "patch": {
                "highlights": [
                    "业务组件维护。",
                    "协助处理交互问题。",
                ],
            },
        },
        target="sections.experience.items.tencent",
    )


def _project_edit() -> dict:
    return _edit(
        {
            "type": "update_item",
            "sectionId": "project",
            "itemId": "resumate",
            "patch": {"description": "面向结构化内容的简历编辑器。"},
        },
        target="sections.project.items.resumate",
    )


def test_prompt_scoped_batch_rejects_every_edit_when_one_is_outside_scope() -> None:
    runner = _runner("只改腾讯实习的两条 bullet，不要删除任何内容，也不要调整顺序。")
    original_resume = runner.draft_resume.copy()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {"edits": [_tencent_bullet_edit(), _project_edit()]},
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["editCount"] == 0
    assert tool.output["fullBatchRequired"] is True
    assert runner.draft_resume == original_resume
    assert runner.edits == []


def test_prompt_scoped_item_and_field_edit_is_allowed() -> None:
    runner = _runner("只改腾讯实习的两条 bullet，不要删除任何内容，也不要调整顺序。")

    tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [_tencent_bullet_edit()]}),
    )

    assert tool.state == "output-available"
    assert runner.draft_resume["sections"][0]["items"][0]["highlights"] == [
        "业务组件维护。",
        "协助处理交互问题。",
    ]


def test_named_item_field_does_not_authorize_sibling_fields_or_basic_data() -> None:
    runner = _runner("只修改腾讯实习的地点。")
    position_edit = _edit(
        {
            "type": "update_item",
            "sectionId": "experience",
            "itemId": "tencent",
            "patch": {"position": "高级前端开发实习生"},
        },
        target="sections.experience.items.tencent",
    )
    basic_location_edit = _edit(
        {
            "type": "replace_field",
            "path": "basic.location",
            "value": "广州",
        },
        target="basic.location",
    )

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {"edits": [position_edit, basic_location_edit]},
        ),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_entity_in_misplaced_position_field_still_rejects_sibling_item() -> None:
    runner = _runner("只改腾讯实习的两条 bullet。")
    sibling_edit = _edit(
        {
            "type": "update_item",
            "sectionId": "experience",
            "itemId": "alibaba",
            "patch": {"highlights": ["整理运营平台的页面维护流程。"]},
        },
        target="sections.experience.items.alibaba",
    )

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {"edits": [_tencent_bullet_edit(), sibling_edit]},
        ),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_project_name_in_tech_stack_still_resolves_the_exact_item() -> None:
    runner = _runner("只修改 ResuMate 项目的 bullet。")
    other_project_edit = _edit(
        {
            "type": "update_item",
            "sectionId": "project",
            "itemId": "other-project",
            "patch": {"highlights": ["完善团队任务的维护流程。"]},
        },
        target="sections.project.items.other-project",
    )

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "update_item",
                            "sectionId": "project",
                            "itemId": "resumate",
                            "patch": {"highlights": ["完善结构化简历编辑流程。"]},
                        },
                        target="sections.project.items.resumate",
                    ),
                    other_project_edit,
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_exclusive_bullet_request_can_safely_resolve_a_unique_dirty_item() -> None:
    resume = _resume()
    experience = resume["sections"][0]
    experience["items"] = [experience["items"][0]]
    experience["items"][0]["position"] = "前端开发实习生"
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-unique-dirty-item",
            role="user",
            text="只改腾讯实习的两条 bullet。",
        ),
        locale="zh",
        resume=resume,
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [_tencent_bullet_edit()]}),
    )

    assert tool.state == "output-available"


def test_unresolved_relative_scope_fails_closed_instead_of_allowing_a_kind() -> None:
    runner = _runner("修改最近一份实习，让表达更精炼。")

    tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [_tencent_bullet_edit()]}),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_unresolved_paragraph_scope_does_not_expand_to_the_whole_resume() -> None:
    runner = _runner("把第一段简历修改得更精炼。")
    summary_edit = _edit(
        {
            "type": "replace_field",
            "path": "basic.summary",
            "value": "专注复杂交互与工程质量。",
        },
        target="basic.summary",
    )

    tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [summary_edit]}),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_explicit_multi_module_prompt_authorizes_only_named_modules() -> None:
    runner = _runner("一次整理 summary、实习、项目和技能，不要删除内容，不要调整顺序。")
    edits = [
        _edit(
            {
                "type": "replace_field",
                "path": "basic.summary",
                "value": "聚焦复杂交互与工程质量。",
            },
            target="basic.summary",
        ),
        _edit(
            {
                "type": "update_item",
                "sectionId": "experience",
                "itemId": "tencent",
                "patch": {"description": "参与内部协作平台的前端开发。"},
            },
            target="sections.experience.items.tencent",
        ),
        _project_edit(),
        _edit(
            {
                "type": "update_item",
                "sectionId": "skills",
                "itemId": "skills-1",
                "patch": {"content": "前端：组件开发；工程：自动化验证"},
            },
            target="sections.skills.items.skills-1",
        ),
    ]

    tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": edits}),
    )

    assert tool.state == "output-available"
    assert len(runner.edits) == 4


def test_edit_plan_cannot_cache_an_operation_outside_prompt_scope() -> None:
    runner = _runner("只改腾讯实习的两条 bullet。")
    steps = [
        {
            "action": "update_item",
            "target": "sections.experience.items.tencent",
            "reason": "更新腾讯实习要点。",
            "operation": _tencent_bullet_edit()["operation"],
        },
        {
            "action": "update_item",
            "target": "sections.project.items.resumate",
            "reason": "越界更新项目。",
            "operation": _project_edit()["operation"],
        },
    ]

    tool, _ = runner._run_local_tool(
        _tool_call("edit_plan", {"steps": steps}),
    )

    assert tool.state == "output-error"
    assert runner.plan == []
    assert runner.planned_edits == []


def test_item_scoped_plan_rejects_a_vague_sections_target() -> None:
    runner = _runner("只改腾讯实习的两条 bullet。")

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_plan",
            {
                "steps": [
                    {
                        "action": "update_item",
                        "target": "sections.items",
                        "reason": "更新经历要点。",
                    },
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert runner.plan == []


def test_draft_rewrite_uses_the_same_atomic_prompt_scope() -> None:
    resume = _resume()
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-scoped-draft-rewrite",
            role="user",
            text="在当前草稿里，只把腾讯实习的两条 bullet 写得更简洁。",
        ),
        locale="zh",
        resume=resume,
        draftState={
            "id": "draft-1",
            "status": "pending",
            "resume": resume,
            "editCount": 1,
            "edits": [_tencent_bullet_edit()],
            "diffs": [],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))
    original_resume = runner.draft_resume.copy()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "draft_rewrite",
            {"edits": [_tencent_bullet_edit(), _project_edit()]},
        ),
    )

    assert tool.state == "output-error"
    assert runner.draft_resume == original_resume
    assert runner.edits == []


def test_pending_follow_up_can_shorten_the_prior_edited_bullet() -> None:
    runner, pending_highlights = _pending_tencent_highlights_runner()
    shortened_highlights = [pending_highlights[0], "定位交互问题。"]

    tool, _ = runner._run_local_tool(
        _tool_call(
            "draft_rewrite",
            {
                "edits": [
                    _edit(
                        {
                            "type": "update_item",
                            "sectionId": "experience",
                            "itemId": "tencent",
                            "patch": {"highlights": shortened_highlights},
                        },
                        target="sections.experience.items.tencent",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-available"
    assert runner.draft_resume["sections"][0]["items"][0]["highlights"] == (
        shortened_highlights
    )


def test_pending_bullet_follow_up_cannot_edit_another_item() -> None:
    runner, _pending_highlights = _pending_tencent_highlights_runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "draft_rewrite",
            {
                "edits": [
                    _edit(
                        {
                            "type": "update_item",
                            "sectionId": "experience",
                            "itemId": "alibaba",
                            "patch": {"highlights": ["维护页面。"]},
                        },
                        target="sections.experience.items.alibaba",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_pending_bullet_follow_up_cannot_edit_a_sibling_field() -> None:
    runner, _pending_highlights = _pending_tencent_highlights_runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "draft_rewrite",
            {
                "edits": [
                    _edit(
                        {
                            "type": "update_item",
                            "sectionId": "experience",
                            "itemId": "tencent",
                            "patch": {"description": "内部协作平台。"},
                        },
                        target="sections.experience.items.tencent",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_pending_bullet_follow_up_still_rejects_unsupported_claims() -> None:
    runner, pending_highlights = _pending_tencent_highlights_runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "draft_rewrite",
            {
                "edits": [
                    _edit(
                        {
                            "type": "update_item",
                            "sectionId": "experience",
                            "itemId": "tencent",
                            "patch": {
                                "highlights": [
                                    pending_highlights[0],
                                    "引入 WCAG 和 Vitest，性能提升 30%。",
                                ],
                            },
                        },
                        target="sections.experience.items.tencent",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["rejectedEdits"][0]["qualityIssue"]["code"] == (
        "unsupported_edit_claim"
    )
    assert runner.edits == []


def test_pending_delete_item_can_be_restored_exactly() -> None:
    runner, deleted_item = _pending_deleted_project_runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "insert_item",
                            "sectionId": "project",
                            "index": 0,
                            "item": deleted_item,
                        },
                        target="sections.project.items.resumate",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-available"
    assert runner.draft_resume["sections"][1]["items"][0] == deleted_item
    assert runner.edits[0].evidence_refs == [
        "resume:item:project:resumate",
        "prompt:current",
    ]


def test_pending_delete_item_does_not_authorize_a_different_item_id() -> None:
    runner, deleted_item = _pending_deleted_project_runner()
    invented_item = {**deleted_item, "id": "invented-project"}

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "insert_item",
                            "sectionId": "project",
                            "item": invented_item,
                        },
                        target="sections.project.items.invented-project",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert runner.edits == []
    assert all(
        item["id"] != "invented-project"
        for item in runner.draft_resume["sections"][1]["items"]
    )


def test_pending_delete_item_cannot_restore_tampered_content() -> None:
    runner, deleted_item = _pending_deleted_project_runner()
    tampered_item = {
        **deleted_item,
        "description": "基于 WCAG 和 Vitest 将性能提升 30%。",
    }

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "insert_item",
                            "sectionId": "project",
                            "item": tampered_item,
                        },
                        target="sections.project.items.resumate",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["rejectedEdits"][0]["qualityIssue"]["code"] == (
        "unsupported_edit_claim"
    )
    assert runner.edits == []


def test_pending_delete_item_restoration_must_keep_original_content() -> None:
    runner, deleted_item = _pending_deleted_project_runner()
    reworded_item = {**deleted_item, "description": "结构化简历工具。"}

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "insert_item",
                            "sectionId": "project",
                            "item": reworded_item,
                        },
                        target="sections.project.items.resumate",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["rejectedEdits"][0]["qualityIssue"]["code"] == (
        "unsupported_edit_claim"
    )
    assert runner.edits == []


def test_pending_delete_section_can_be_restored_exactly() -> None:
    runner, deleted_section = _pending_deleted_section_runner()

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "insert_section",
                            "index": 1,
                            "section": deleted_section,
                        },
                        target="sections.project",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-available"
    assert runner.draft_resume["sections"][1] == deleted_section
    assert runner.edits[0].evidence_refs == [
        "resume:section:project",
        "prompt:current",
    ]


def test_pending_delete_section_does_not_authorize_a_different_section_id() -> None:
    runner, deleted_section = _pending_deleted_section_runner()
    invented_section = {**deleted_section, "id": "invented-section"}

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "insert_section",
                            "section": invented_section,
                        },
                        target="sections.invented-section",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_pending_delete_section_restoration_must_keep_original_content() -> None:
    runner, deleted_section = _pending_deleted_section_runner()
    renamed_section = {**deleted_section, "title": "精选项目"}

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_execute",
            {
                "edits": [
                    _edit(
                        {
                            "type": "insert_section",
                            "section": renamed_section,
                        },
                        target="sections.project",
                    ),
                ],
            },
        ),
    )

    assert tool.state == "output-error"
    assert tool.output["rejectedEdits"][0]["qualityIssue"]["code"] == (
        "unsupported_edit_claim"
    )
    assert runner.edits == []


def test_empty_edit_plan_call_cannot_generate_a_deterministic_plan() -> None:
    runner = _runner("优化个人 summary。")
    runner.analysis = runner.executor.analyze_resume()

    tool, _ = runner._run_local_tool(
        _tool_call("edit_plan", {}),
    )

    assert tool.state == "output-error"
    assert runner.plan == []
    assert runner.planned_edits == []


def test_empty_edit_execute_call_cannot_generate_deterministic_edits() -> None:
    runner = _runner("优化个人 summary。")
    runner.analysis = runner.executor.analyze_resume()
    plan_tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_plan",
            {
                "steps": [
                    {
                        "action": "replace_field",
                        "target": "basic.summary",
                        "reason": "聚焦个人简介。",
                    },
                ],
            },
        ),
    )
    original_resume = runner.draft_resume.copy()

    execute_tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {}),
    )

    assert plan_tool.state == "output-available"
    assert execute_tool.state == "output-error"
    assert runner.draft_resume == original_resume
    assert runner.edits == []


def test_negated_delete_and_reorder_phrases_never_grant_destructive_intent() -> None:
    prompt = "优化腾讯实习，但不要删除任何内容，也不要调整顺序。"

    assert has_explicit_delete_intent(prompt) is False
    assert has_explicit_reorder_intent(prompt) is False


def test_negative_constraints_block_destructive_operations() -> None:
    runner = _runner("优化腾讯实习 bullet，但不要删除内容，也不要调整顺序。")
    delete_edit = _edit(
        {
            "type": "delete_item",
            "sectionId": "experience",
            "itemId": "tencent",
        },
        target="sections.experience.items.tencent",
    )
    reorder_edit = _edit(
        {
            "type": "reorder_sections",
            "sectionIds": ["project", "experience", "skills"],
        },
        target="sections",
    )

    delete_tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [delete_edit]}),
    )
    reorder_tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [reorder_edit]}),
    )

    assert delete_tool.state == "output-error"
    assert reorder_tool.state == "output-error"
    assert runner.edits == []


def test_bullet_scope_never_authorizes_deleting_the_whole_item() -> None:
    runner = _runner("只删除腾讯实习的两条 bullet。")
    delete_item = _edit(
        {
            "type": "delete_item",
            "sectionId": "experience",
            "itemId": "tencent",
        },
        target="sections.experience.items.tencent",
    )

    tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [delete_item]}),
    )

    assert tool.state == "output-error"
    assert runner.edits == []


def test_same_kind_move_keeps_the_source_item_as_insert_evidence() -> None:
    resume = _resume()
    project_section = resume["sections"][1]
    source_item = project_section["items"][0]
    source_item.update(
        {
            "role": "Frontend engineer",
            "techStack": ["ResuMate", "React"],
            "period": "2026",
            "description": "AI resume editor",
            "highlights": ["Built a structured editing workflow."],
        },
    )
    resume["sections"].append(
        {
            "id": "selected-projects",
            "kind": "project",
            "title": "精选项目",
            "items": [],
        },
    )
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-move-project-with-evidence",
            role="user",
            text="把 ResuMate 项目移动到精选项目。",
        ),
        locale="zh",
        resume=resume,
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_move_item",
            {
                "fromSectionId": "project",
                "toSectionId": "selected-projects",
                "itemId": "resumate",
                "reason": "移动用户指定的项目。",
            },
        ),
    )

    assert tool.state == "output-available"
    assert [item["id"] for item in runner.draft_resume["sections"][1]["items"]] == [
        "other-project"
    ]
    assert runner.draft_resume["sections"][-1]["items"] == [source_item]
    assert runner.edits[1].evidence_refs == ["resume:item:project:resumate"]


def test_merge_uses_every_source_item_as_candidate_evidence() -> None:
    resume = _resume()
    project_section = resume["sections"][1]
    project_section["items"] = [
        {
            "id": "alpha",
            "name": "Alpha",
            "role": "开发者",
            "techStack": ["React"],
            "period": "2026",
            "url": "",
            "description": "组件库",
            "highlights": ["完成组件库。"],
        },
        {
            "id": "beta",
            "name": "Beta",
            "role": "开发者",
            "techStack": ["Python"],
            "period": "2026",
            "url": "",
            "description": "支付服务",
            "highlights": ["完成结算链路。"],
        },
    ]
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-merge-projects-with-evidence",
            role="user",
            text="合并 Alpha 和 Beta 两个项目，保留原有事实。",
        ),
        locale="zh",
        resume=resume,
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))

    tool, _ = runner._run_local_tool(
        _tool_call(
            "edit_merge_items",
            {
                "sectionId": "project",
                "itemIds": ["alpha", "beta"],
                "mergedItem": {
                    "name": "Alpha",
                    "role": "开发者",
                    "techStack": ["React", "Python"],
                    "period": "2026",
                    "url": "",
                    "description": "组件库与支付服务",
                    "highlights": ["完成组件库。", "完成结算链路。"],
                },
                "reason": "合并用户指定的两个项目。",
            },
        ),
    )

    assert tool.state == "output-available"
    assert len(runner.draft_resume["sections"][1]["items"]) == 1
    assert runner.edits[0].evidence_refs == [
        "resume:item:project:alpha",
        "resume:item:project:beta",
        "prompt:current",
    ]


def test_affirmative_delete_and_reorder_phrases_still_grant_intent() -> None:
    assert has_explicit_delete_intent("删除空白项目") is True
    assert has_explicit_reorder_intent("把项目经历移动到实习经历前面") is True


def test_negative_constraints_alone_do_not_authorize_any_draft_write() -> None:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-negative-constraints-only",
            role="user",
            text="不要删除任何内容，也不要调整顺序。",
        ),
        locale="zh",
        resume=_resume(),
    )

    assert capability_policy_for_request(request).mode == AgentCapabilityMode.READ_ONLY


def test_unsupported_claims_cannot_reach_the_draft_resume() -> None:
    runner = _runner(
        "优化项目经历；为了匹配岗位直接加上 WCAG、Vitest、CI 和提升 30%，"
        "这些经历目前没有证据。",
    )
    original_resume = runner.draft_resume.copy()
    claim_edit = _edit(
        {
            "type": "update_item",
            "sectionId": "project",
            "itemId": "resumate",
            "patch": {
                "highlights": [
                    "依据 WCAG，引入 Vitest 和 CI，交付效率提升 30%。",
                ],
            },
        },
        target="sections.project.items.resumate",
    )

    tool, _ = runner._run_local_tool(
        _tool_call("edit_execute", {"edits": [claim_edit]}),
    )

    assert tool.state == "output-error"
    assert (
        tool.output["rejectedEdits"][0]["qualityIssue"]["code"]
        == "unsupported_edit_claim"
    )
    assert runner.draft_resume == original_resume
    assert runner.edits == []
