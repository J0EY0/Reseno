import asyncio
import json

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentResumeEditSuggestion,
)
from app.services.agent.evidence import ground_edit_evidence
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmToolCall


def _resume() -> dict[str, object]:
    return {
        "basic": {"summary": "Frontend engineer."},
        "sections": [
            {
                "id": "project",
                "kind": "project",
                "items": [
                    {
                        "id": "project-1",
                        "title": "Resume editor",
                        "highlights": ["Built an accessible editor."],
                    },
                ],
            },
        ],
    }


def _edit(
    *,
    evidence_refs: list[str] | None = None,
) -> AgentResumeEditSuggestion:
    return AgentResumeEditSuggestion(
        id="edit-1",
        title="Tighten project bullet",
        target="sections.project.items.project-1",
        reason="Make the verified contribution clearer.",
        operation={
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {"highlights": ["Built an accessible resume editor."]},
        },
        evidenceRefs=evidence_refs or [],
        status="executed",
    )


def test_missing_model_evidence_is_inferred_from_operation() -> None:
    edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-inferred",
                role="user",
                text="Rewrite the existing project bullet.",
            ),
        ),
        [_edit()],
    )

    assert issues == []
    assert edits[0].evidence_refs == [
        "resume:item:project:project-1",
        "prompt:current",
    ]


def test_current_attachment_is_valid_candidate_evidence() -> None:
    edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-attachment",
                role="user",
                text="Use the attached project notes.",
                files=[
                    {
                        "id": "attachment-1",
                        "filename": "notes.pdf",
                        "mediaType": "application/pdf",
                    },
                ],
            ),
        ),
        [_edit(evidence_refs=["attachment:attachment-1"])],
    )

    assert issues == []
    assert edits[0].evidence_refs == ["attachment:attachment-1"]


def test_public_target_source_cannot_be_candidate_evidence() -> None:
    edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-public-source",
                role="user",
                text="Tailor this bullet to the role.",
            ),
        ),
        [_edit(evidence_refs=["web:https://example.com/job"])],
    )

    assert edits[0].evidence_refs == ["web:https://example.com/job"]
    assert issues == [
        {
            "code": "invalid_edit_evidence",
            "severity": "error",
            "target": "sections.project.items.project-1",
            "scope": "evidence",
            "operationIndex": 1,
            "invalidEvidenceRefs": ["web:https://example.com/job"],
        },
    ]


def test_edit_response_serializes_public_evidence_refs_alias() -> None:
    payload = _edit(
        evidence_refs=["resume:item:project:project-1"],
    ).model_dump(by_alias=True)

    assert payload["evidenceRefs"] == ["resume:item:project:project-1"]
    assert "evidence_refs" not in payload


def test_summary_technology_labels_are_grounded_by_cited_resume_items() -> None:
    resume = {
        "schemaVersion": 2,
        "basic": {
            "name": "候选人",
            "headline": "前端工程师",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "前端工程师，重视可维护性、性能与用户体验。",
            "customFields": [],
        },
        "sections": [
            {
                "id": "project",
                "kind": "project",
                "title": "项目经历",
                "items": [
                    {
                        "id": "project-1",
                        "name": "AI 应用",
                        "role": "前端工程师",
                        "techStack": ["React", "TypeScript"],
                        "period": "",
                        "url": "",
                        "description": "专注前端工程与 AI 应用落地。",
                        "highlights": [],
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
                        "content": "React、TypeScript",
                    },
                ],
            },
        ],
    }
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-summary-cited-technologies",
            role="user",
            text="请根据项目和技能事实修改 summary。",
        ),
        locale="zh",
        resume=resume,
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))
    summary = (
        "专注前端工程与 AI 应用落地，熟悉 React 与 TypeScript 技术栈，"
        "重视可维护性、性能与用户体验。"
    )
    arguments = {
        "edits": [
            {
                "title": "更新个人简介",
                "target": "basic.summary",
                "reason": "汇总简历已有事实。",
                "evidenceRefs": [
                    "resume:item:project:project-1",
                    "resume:item:skills:skills-1",
                ],
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": summary,
                },
            },
        ],
    }

    tool, _ = runner._run_local_tool(
        LlmToolCall(
            id="call-summary-cited-technologies",
            name="edit_execute",
            arguments=arguments,
            raw_arguments=json.dumps(arguments, ensure_ascii=False),
        ),
    )

    assert tool.state == "output-available", json.dumps(
        tool.output,
        ensure_ascii=False,
    )
    assert runner.draft_resume["basic"]["summary"] == summary


def test_existing_tailwind_label_can_be_normalized_through_public_runner() -> None:
    resume = {
        "schemaVersion": 2,
        "basic": {
            "name": "候选人",
            "headline": "前端工程师",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "前端工程师。",
            "customFields": [],
        },
        "sections": [
            {
                "id": "project",
                "kind": "project",
                "title": "项目经历",
                "items": [
                    {
                        "id": "project-1",
                        "name": "简历编辑器",
                        "role": "",
                        "techStack": ["TypeScript · Tailwind"],
                        "period": "",
                        "url": "",
                        "description": "构建结构化简历编辑器。",
                        "highlights": [],
                    },
                ],
            },
        ],
    }
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-normalize-tailwind-label",
            role="user",
            text=(
                "请整理项目经历的技术栈，把已有的 TypeScript · Tailwind "
                "规范为 TypeScript 和 Tailwind CSS，不要新增事实。"
            ),
        ),
        locale="zh",
        resume=resume,
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))
    arguments = {
        "edits": [
            {
                "title": "规范项目技术栈",
                "target": "sections.project.items.project-1.techStack",
                "reason": "拆分已有技术栈并规范 Tailwind 名称。",
                "evidenceRefs": ["resume:item:project:project-1"],
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"techStack": ["TypeScript", "Tailwind CSS"]},
                },
            },
        ],
    }

    async def scenario() -> None:
        tool, _ = await runner.run(
            LlmToolCall(
                id="call-normalize-tailwind-label",
                name="edit_execute",
                arguments=arguments,
                raw_arguments=json.dumps(arguments, ensure_ascii=False),
            ),
            AgentRuntimeContext(),
        )

        assert tool.state == "output-available", json.dumps(
            tool.output,
            ensure_ascii=False,
        )
        project = runner.draft_resume["sections"][0]["items"][0]
        assert project["techStack"] == ["TypeScript", "Tailwind CSS"]

    asyncio.run(scenario())


def test_tailwind_alias_does_not_ground_other_new_project_claims() -> None:
    resume = _resume()
    project = resume["sections"][0]["items"][0]
    project["role"] = ""
    project["techStack"] = ["TypeScript · Tailwind"]
    edit = AgentResumeEditSuggestion(
        id="edit-tailwind-with-unsupported-claims",
        title="Reorganize project fields",
        target="sections.project.items.project-1",
        reason="Move project details into their structured fields.",
        operation={
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {
                "role": "前端开发",
                "techStack": [
                    "TypeScript",
                    "Tailwind CSS",
                    "WCAG",
                    "Vitest",
                    "CI",
                ],
                "highlights": ["性能提升 30%。"],
            },
        },
        evidenceRefs=["resume:item:project:project-1"],
        status="executed",
    )

    _edits, issues = ground_edit_evidence(
        resume,
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-tailwind-with-unsupported-claims",
                role="user",
                text=(
                    "请整理项目字段，并添加前端开发、WCAG、Vitest、CI 和性能提升 30%。"
                ),
            ),
        ),
        [edit],
    )

    unsupported = [
        issue for issue in issues if issue["code"] == "unsupported_edit_claim"
    ]
    assert unsupported[0]["claims"] == [
        "30%",
        "CI",
        "Vitest",
        "WCAG",
        "text:前端开发",
    ]


def _claim_edit(
    text: str,
    *,
    evidence_refs: list[str] | None = None,
) -> AgentResumeEditSuggestion:
    return AgentResumeEditSuggestion(
        id="edit-claim",
        title="Rewrite project claim",
        target="sections.project.items.project-1",
        reason="Make the contribution concrete.",
        operation={
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {"highlights": [text]},
        },
        evidenceRefs=evidence_refs or [],
        status="executed",
    )


def test_instruction_text_is_not_evidence_for_new_claims() -> None:
    edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-unsupported-claim",
                role="user",
                text=(
                    "为了匹配岗位，请直接加上 WCAG、Vitest 和 CI，"
                    "再写性能提升 30%，这些经历目前没有证据。"
                ),
            ),
        ),
        [_claim_edit("基于 WCAG，引入 Vitest 和 CI，性能提升 30%。")],
    )

    assert edits[0].evidence_refs == [
        "resume:item:project:project-1",
        "prompt:current",
    ]
    unsupported = [
        issue for issue in issues if issue["code"] == "unsupported_edit_claim"
    ]
    assert unsupported == [
        {
            "code": "unsupported_edit_claim",
            "severity": "error",
            "target": "sections.project.items.project-1",
            "scope": "evidence",
            "operationIndex": 1,
            "claims": ["30%", "CI", "Vitest", "WCAG"],
        },
    ]


def test_imperative_claim_wording_is_not_a_candidate_fact() -> None:
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-imperative-claim",
                role="user",
                text=(
                    "为了匹配岗位，请写成：负责 WCAG、Vitest、CI、Kafka 和 Playwright，"
                    "并把性能提升写成 30%。"
                ),
            ),
        ),
        [
            _claim_edit(
                "负责 WCAG、Vitest、CI、Kafka 和 Playwright，性能提升 30%。",
            ),
        ],
    )

    unsupported = [
        issue for issue in issues if issue["code"] == "unsupported_edit_claim"
    ]
    assert unsupported[0]["claims"] == [
        "30%",
        "CI",
        "Kafka",
        "Playwright",
        "Vitest",
        "WCAG",
    ]


def test_unknown_tech_stack_entry_requires_candidate_evidence() -> None:
    edit = AgentResumeEditSuggestion(
        id="edit-unknown-stack",
        title="Update project stack",
        target="sections.project.items.project-1",
        reason="Add a requested technology.",
        operation={
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {"techStack": ["NicheDB"]},
        },
        status="executed",
    )
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-unknown-stack",
                role="user",
                text="为了匹配岗位，请直接把 NicheDB 加到技术栈。",
            ),
        ),
        [edit],
    )

    unsupported = [
        issue for issue in issues if issue["code"] == "unsupported_edit_claim"
    ]
    assert unsupported[0]["claims"] == ["NicheDB"]


def test_strengthened_ownership_and_chinese_metric_require_evidence() -> None:
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-strengthened-ownership",
                role="user",
                text=("为了匹配岗位，请改成主导跨部门交付，并写效率提升百分之三十。"),
            ),
        ),
        [_claim_edit("主导跨部门交付，效率提升百分之三十。")],
    )

    unsupported = [
        issue for issue in issues if issue["code"] == "unsupported_edit_claim"
    ]
    assert set(unsupported[0]["claims"]) == {"主导", "跨部门", "百分之三十"}


def test_unrelated_business_facts_are_rejected_without_candidate_evidence() -> None:
    claims = [
        "设计并落地客户增长平台，推动跨区域业务协同。",
        "获得年度最佳员工奖并负责十人团队。",
        "负责支付结算核心链路，保障高峰稳定性。",
    ]

    for index, claim in enumerate(claims):
        _edits, issues = ground_edit_evidence(
            _resume(),
            AgentChatRequest(
                message=AgentConversationItem(
                    id=f"turn-edit-evidence-unrelated-business-{index}",
                    role="user",
                    text=f"为了匹配岗位，请直接写成：{claim}",
                ),
            ),
            [_claim_edit(claim)],
        )

        unsupported = [
            issue for issue in issues if issue["code"] == "unsupported_edit_claim"
        ]
        assert unsupported


def test_grounded_prefix_cannot_hide_an_invented_business_fact() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"] = ["负责平台开发。"]
    claims = [
        "负责平台开发，获得年度最佳员工并管理十人团队。",
        "负责平台开发，搭建支付核心链路并推动公司上市。",
        "负责平台开发并搭建支付核心链路。",
        "负责平台开发且覆盖全球客户。",
        "负责平台开发与公司战略落地。",
    ]

    for index, claim in enumerate(claims):
        _edits, issues = ground_edit_evidence(
            resume,
            AgentChatRequest(
                message=AgentConversationItem(
                    id=f"turn-edit-evidence-grounded-prefix-{index}",
                    role="user",
                    text="请改得更有影响力，但不要编造。",
                ),
            ),
            [_claim_edit(claim)],
        )

        unsupported = [
            issue for issue in issues if issue["code"] == "unsupported_edit_claim"
        ]
        assert unsupported


def test_generic_grounded_prefix_cannot_support_an_unrelated_suffix() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"] = ["负责平台开发。"]
    claims = [
        "负责平台支付核心链路。",
        "负责平台全球客户交付。",
        "负责平台人工智能推荐系统。",
        "负责平台安全架构。",
        "负责平台开发安全架构。",
        "负责移动端平台开发。",
    ]

    for index, claim in enumerate(claims):
        _edits, issues = ground_edit_evidence(
            resume,
            AgentChatRequest(
                message=AgentConversationItem(
                    id=f"turn-edit-evidence-generic-prefix-{index}",
                    role="user",
                    text="请优化这条项目描述，不要编造。",
                ),
            ),
            [_claim_edit(claim)],
        )

        unsupported = [
            issue for issue in issues if issue["code"] == "unsupported_edit_claim"
        ]
        assert unsupported


def test_factual_prefix_does_not_turn_an_imperative_suffix_into_evidence() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"] = ["负责平台开发。"]
    _edits, issues = ground_edit_evidence(
        resume,
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-imperative-suffix",
                role="user",
                text="我负责平台开发，请写成我推动公司上市。",
            ),
        ),
        [_claim_edit("我推动公司上市。")],
    )

    unsupported = [
        issue for issue in issues if issue["code"] == "unsupported_edit_claim"
    ]
    assert unsupported


def test_explicit_business_fact_in_prompt_can_be_rewritten() -> None:
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-factual-business",
                role="user",
                text=(
                    "候选人事实：我负责支付结算核心链路，保障高峰稳定性。请据此改写。"
                ),
            ),
        ),
        [_claim_edit("负责支付结算核心链路，保障高峰稳定性。")],
    )

    assert issues == []


def test_denial_clause_does_not_erase_a_separate_candidate_fact() -> None:
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-fact-with-denial",
                role="user",
                text="我负责支付链路，请不要编造其他内容，帮我优化。",
            ),
        ),
        [_claim_edit("负责支付链路。")],
    )

    assert issues == []


def test_denied_unknown_skills_do_not_erase_a_confirmed_skill() -> None:
    edit = AgentResumeEditSuggestion(
        id="edit-confirmed-stack",
        title="Update project stack",
        target="sections.project.items.project-1",
        reason="Add the confirmed technology.",
        operation={
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {"techStack": ["React"]},
        },
        status="executed",
    )
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-skill-with-denial",
                role="user",
                text=(
                    "我在项目中使用了 React，不要添加我没做过的技能，"
                    "请把 React 加入技术栈。"
                ),
            ),
        ),
        [edit],
    )

    assert issues == []


def test_factual_prompt_can_support_ownership_and_chinese_metric() -> None:
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-factual-ownership",
                role="user",
                text=("候选人事实：我主导跨部门交付，效率提升百分之三十。请据此改写。"),
            ),
        ),
        [_claim_edit("主导跨部门交付，效率提升百分之三十。")],
    )

    assert issues == []


def test_factual_prompt_can_support_new_metrics_and_technology_claims() -> None:
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-supported-prompt",
                role="user",
                text=(
                    "补充候选人事实：我在这个项目中依据 WCAG 改进可访问性，"
                    "使用 Vitest 并接入 CI，回归耗时降低 30%。请据此改写。"
                ),
            ),
        ),
        [_claim_edit("依据 WCAG，引入 Vitest 和 CI，回归耗时降低 30%。")],
    )

    assert issues == []


def test_existing_resume_claims_remain_valid_evidence() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"] = [
        "依据 WCAG，使用 Vitest 接入 CI，回归耗时降低 30%。",
    ]

    _edits, issues = ground_edit_evidence(
        resume,
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-edit-evidence-existing-claim",
                role="user",
                text="精简现有项目要点，不要新增事实。",
            ),
        ),
        [_claim_edit("使用 WCAG、Vitest 和 CI，将回归耗时降低 30%。")],
    )

    assert issues == []


def test_current_attachment_can_support_new_claims(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.services.agent.evidence.attachment_text",
        lambda _session_id, _file: (
            "项目事实：依据 WCAG 改进可访问性，使用 Vitest 接入 CI，回归耗时降低 30%。"
        ),
    )
    _edits, issues = ground_edit_evidence(
        _resume(),
        AgentChatRequest(
            resumeId="resume-1",
            expectedRevision="revision-1",
            message=AgentConversationItem(
                id="turn-edit-evidence-supported-attachment",
                role="user",
                text="根据附件中的项目事实改写这条经历。",
                files=[
                    {
                        "id": "attachment-1",
                        "filename": "facts.txt",
                        "mediaType": "text/plain",
                    },
                ],
            ),
        ),
        [
            _claim_edit(
                "依据 WCAG，引入 Vitest 和 CI，回归耗时降低 30%。",
                evidence_refs=["attachment:attachment-1"],
            ),
        ],
    )

    assert issues == []
