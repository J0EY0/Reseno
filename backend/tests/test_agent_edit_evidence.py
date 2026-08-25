from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentResumeEditSuggestion,
)
from app.services.agent.evidence import (
    ground_edit_evidence,
    historical_prompt_evidence_ref,
)


def _resume() -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "basic": {
            "name": "候选人",
            "headline": "前端工程师",
            "phone": "",
            "email": "",
            "location": "杭州",
            "avatar": "",
            "summary": "专注前端产品体验。",
            "customFields": [],
        },
        "sections": [
            {
                "id": "project",
                "kind": "project",
                "title": "项目经历",
                "items": [
                    {
                        "id": "target",
                        "name": "Resume editor",
                        "role": "前端工程师",
                        "techStack": ["React", "TypeScript"],
                        "period": "2024",
                        "url": "",
                        "description": "Built an accessible editor.",
                        "highlights": ["Reduced regression time by 30%."],
                    },
                    {
                        "id": "sibling",
                        "name": "Event platform",
                        "role": "平台工程师",
                        "techStack": ["Kafka"],
                        "period": "2023",
                        "url": "",
                        "description": "Processed event streams.",
                        "highlights": ["Handled 40k events."],
                    },
                ],
            },
            {
                "id": "skills",
                "kind": "simple_list",
                "title": "技能",
                "items": [{"id": "skills-1", "content": "Python、Docker"}],
            },
        ],
    }


def _request(
    text: str,
    *,
    resume: dict[str, Any] | None = None,
    messages: list[AgentConversationItem] | None = None,
    files: list[dict[str, Any]] | None = None,
    resume_id: str | None = None,
) -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="current-turn",
            role="user",
            text=text,
            files=files or [],
        ),
        messages=messages or [],
        resume=resume or _resume(),
        resumeId=resume_id,
        expectedRevision="1" if resume_id else None,
        locale="zh",
    )


def _edit(
    operation: dict[str, Any],
    *,
    evidence_refs: list[str] | None = None,
    target: str = "sections.project.items.target",
    edit_id: str = "edit-1",
) -> AgentResumeEditSuggestion:
    return AgentResumeEditSuggestion(
        id=edit_id,
        title="Edit resume",
        target=target,
        reason="Execute the requested edit.",
        operation=operation,
        evidenceRefs=evidence_refs or [],
        status="executed",
    )


def _update_target(
    patch: dict[str, Any],
    *,
    evidence_refs: list[str] | None = None,
    edit_id: str = "edit-target",
) -> AgentResumeEditSuggestion:
    return _edit(
        {
            "type": "update_item",
            "sectionId": "project",
            "itemId": "target",
            "patch": patch,
        },
        evidence_refs=evidence_refs,
        edit_id=edit_id,
    )


def _unsupported(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return next(issue for issue in issues if issue["code"] == "unsupported_edit_claim")


def test_missing_model_refs_are_inferred_from_operation_target() -> None:
    edits, issues = ground_edit_evidence(
        _resume(),
        _request("Rewrite the existing description."),
        [_update_target({"description": "Made the editor easier to use."})],
    )

    assert issues == []
    assert edits[0].evidence_refs == [
        "resume:item:project:target",
        "prompt:current",
    ]


def test_invalid_ref_is_rejected() -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("Rewrite the description."),
        [
            _update_target(
                {"description": "Made the editor easier to use."},
                evidence_refs=["web:https://example.com/job"],
            ),
        ],
    )

    assert issues == [
        {
            "code": "invalid_edit_evidence",
            "severity": "error",
            "target": "sections.project.items.target",
            "scope": "evidence",
            "operationIndex": 1,
            "invalidEvidenceRefs": ["web:https://example.com/job"],
        },
    ]


def test_operation_without_an_inferable_ref_is_rejected() -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("Keep the current order."),
        [
            _edit(
                {"type": "reorder_sections", "sectionIds": []},
                target="sections",
            ),
        ],
    )

    assert [issue["code"] for issue in issues] == ["missing_edit_evidence"]


def test_current_user_message_supports_objective_material() -> None:
    prompt = "候选人事实：项目角色是 AI 工程师，使用 Kafka，吞吐提升 45%。"
    _, issues = ground_edit_evidence(
        _resume(),
        _request(prompt),
        [
            _update_target(
                {
                    "role": "AI 工程师",
                    "techStack": ["React", "TypeScript", "Kafka"],
                    "highlights": ["吞吐提升 45%。"],
                },
                evidence_refs=[
                    "resume:item:project:target",
                    "prompt:current",
                ],
            ),
        ],
    )

    assert issues == []


def test_historical_user_message_supports_material_without_phrase_routing() -> None:
    source_id = "history-material"
    source_ref = historical_prompt_evidence_ref(source_id)
    messages = [
        AgentConversationItem(
            id=source_id,
            role="user",
            text="Please add Kafka and the measured 45% improvement.",
        ),
    ]

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Use my earlier details.", messages=messages),
        [
            _update_target(
                {
                    "techStack": ["React", "TypeScript", "Kafka"],
                    "highlights": ["Improved throughput by 45%."],
                },
                evidence_refs=["resume:item:project:target", source_ref],
            ),
        ],
    )

    assert issues == []


def test_assistant_history_is_not_candidate_evidence() -> None:
    assistant_id = "assistant-material"
    assistant_ref = historical_prompt_evidence_ref(assistant_id)
    messages = [
        AgentConversationItem(
            id=assistant_id,
            role="assistant",
            text="You used Kafka and improved throughput by 45%.",
        ),
    ]

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Use verified facts.", messages=messages),
        [
            _update_target(
                {
                    "techStack": ["React", "TypeScript", "Kafka"],
                    "highlights": ["Improved throughput by 45%."],
                },
                evidence_refs=[assistant_ref],
            ),
        ],
    )

    assert {issue["code"] for issue in issues} == {
        "invalid_edit_evidence",
        "unsupported_edit_claim",
    }


def test_duplicate_historical_user_ids_are_not_addressable() -> None:
    source_ref = historical_prompt_evidence_ref("duplicate")
    messages = [
        AgentConversationItem(
            id="duplicate",
            role="user",
            text="I used Kafka.",
        ),
        AgentConversationItem(
            id="duplicate",
            role="user",
            text="I did not use Kafka.",
        ),
    ]

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Use verified facts.", messages=messages),
        [
            _update_target(
                {"techStack": ["React", "TypeScript", "Kafka"]},
                evidence_refs=[source_ref],
            ),
        ],
    )

    assert {issue["code"] for issue in issues} == {
        "invalid_edit_evidence",
        "unsupported_edit_claim",
    }


def test_attachment_supports_objective_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.agent.evidence.attachment_text",
        lambda _session_id, _file: "Project used Kafka and improved throughput by 45%.",
    )
    files = [
        {"id": "notes", "filename": "notes.pdf", "mediaType": "application/pdf"},
    ]

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Use the attachment.", files=files, resume_id="resume1"),
        [
            _update_target(
                {
                    "techStack": ["React", "TypeScript", "Kafka"],
                    "highlights": ["Improved throughput by 45%."],
                },
                evidence_refs=[
                    "resume:item:project:target",
                    "attachment:notes",
                ],
            ),
        ],
    )

    assert issues == []


def test_unsupported_number_technology_and_identity_are_rejected() -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("Improve the existing project wording."),
        [
            _update_target(
                {
                    "role": "平台工程师",
                    "techStack": ["React", "TypeScript", "Kafka"],
                    "highlights": ["Improved throughput by 45%."],
                },
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )

    assert set(_unsupported(issues)["claims"]) == {
        "45%",
        "Kafka",
        "identity:role:平台工程师",
    }


def test_number_claim_spacing_before_percent_is_not_new_evidence() -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("只修复百分号前的空格。"),
        [
            _update_target(
                {"highlights": ["Reduced regression time by 30 %."]},
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )

    assert issues == []


def test_number_claim_spacing_before_unit_is_not_new_evidence() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"].append(
        "Completed the render in 120ms.",
    )

    _, issues = ground_edit_evidence(
        resume,
        _request("只修复单位前的空格。", resume=resume),
        [
            _update_target(
                {
                    "highlights": [
                        "Reduced regression time by 30%.",
                        "Completed the render in 120 ms.",
                    ],
                },
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )

    assert issues == []


def test_changed_number_with_unit_still_requires_evidence() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["highlights"].append(
        "Completed the render in 120ms.",
    )

    _, issues = ground_edit_evidence(
        resume,
        _request("优化项目描述。", resume=resume),
        [
            _update_target(
                {
                    "highlights": [
                        "Reduced regression time by 30%.",
                        "Completed the render in 121 ms.",
                    ],
                },
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )

    assert _unsupported(issues)["claims"] == ["121ms"]


def test_identity_matching_ignores_only_latin_cjk_boundary_spacing() -> None:
    resume = _resume()
    resume["sections"][0]["items"][0]["name"] = (
        "ResuMate AI Agent简历制作网站"
    )

    _, spacing_issues = ground_edit_evidence(
        resume,
        _request("修复项目字段错位。", resume=resume),
        [
            _update_target(
                {"name": "ResuMate AI Agent 简历制作网站"},
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )
    _, changed_identity_issues = ground_edit_evidence(
        resume,
        _request("修复项目字段错位。", resume=resume),
        [
            _update_target(
                {"name": "ResuMate AI Assistant 简历制作网站"},
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )

    assert spacing_issues == []
    assert _unsupported(changed_identity_issues)["claims"] == [
        "identity:name:ResuMate AI Assistant 简历制作网站",
    ]


def test_free_text_wording_is_not_an_online_claim_gate() -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("重组现有腾讯实习内容并提升信息密度，不添加客观事实。"),
        [
            _update_target(
                {
                    "description": "负责梳理后台管理系统，并通过联调提升体验一致性。",
                    "highlights": [
                        "优化页面状态管理，从而降低状态复杂度。",
                        "覆盖样式相关的回归场景。",
                        "与测试、设计进行联调。",
                        "对应页面状态管理相关代码。",
                        "协同设计与 QA 把控 UI 一致性与回归质量。",
                    ],
                },
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )

    assert issues == []


def test_headline_can_synthesize_existing_resume_evidence() -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("Summarize the existing resume in the headline."),
        [
            _edit(
                {
                    "type": "replace_field",
                    "path": "basic.headline",
                    "value": "React 与 TypeScript 前端开发者",
                },
                target="basic.headline",
            ),
        ],
    )

    assert issues == []


def test_summary_prose_is_ignored_but_objective_material_is_checked() -> None:
    prose_edit = _edit(
        {
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Turns complex product needs into clear experiences.",
        },
        evidence_refs=["resume:basic:summary"],
        target="basic.summary",
        edit_id="summary-prose",
    )
    material_edit = _edit(
        {
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Built Kafka systems with 45% higher throughput.",
        },
        evidence_refs=["resume:basic:summary"],
        target="basic.summary",
        edit_id="summary-material",
    )

    _, prose_issues = ground_edit_evidence(
        _resume(),
        _request("Rewrite the summary."),
        [prose_edit],
    )
    _, material_issues = ground_edit_evidence(
        _resume(),
        _request("Rewrite the summary."),
        [material_edit],
    )

    assert prose_issues == []
    assert set(_unsupported(material_issues)["claims"]) == {"45%"}


def test_target_item_can_support_reorganized_material() -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("Reorganize the current project facts."),
        [
            _update_target(
                {
                    "description": (
                        "Built the editor with React and reduced regression "
                        "time by 30%."
                    ),
                },
                evidence_refs=["resume:item:project:target"],
            ),
        ],
    )

    assert issues == []


@pytest.mark.parametrize(
    "foreign_ref",
    (
        "resume:item:project:sibling",
        "resume:section:skills",
    ),
)
def test_foreign_resume_scope_cannot_prove_target_item_material(
    foreign_ref: str,
) -> None:
    _, issues = ground_edit_evidence(
        _resume(),
        _request("Update the target project."),
        [
            _update_target(
                {"techStack": ["React", "TypeScript", "Kafka"]},
                evidence_refs=[foreign_ref],
            ),
        ],
    )

    assert _unsupported(issues)["claims"] == ["Kafka"]


def test_complete_merge_can_use_deleted_source_item() -> None:
    update = _update_target(
        {
            "techStack": ["React", "TypeScript", "Kafka"],
            "highlights": ["Handled 40k events."],
        },
        evidence_refs=[
            "resume:item:project:target",
            "resume:item:project:sibling",
        ],
        edit_id="merge-target",
    )
    delete = _edit(
        {
            "type": "delete_item",
            "sectionId": "project",
            "itemId": "sibling",
        },
        evidence_refs=["resume:item:project:sibling"],
        target="sections.project.items.sibling",
        edit_id="merge-delete",
    )

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Merge the sibling project into the target."),
        [update, delete],
    )

    assert issues == []


def test_incomplete_merge_cannot_borrow_source_item() -> None:
    update = _update_target(
        {"techStack": ["React", "TypeScript", "Kafka"]},
        evidence_refs=[
            "resume:item:project:target",
            "resume:item:project:sibling",
        ],
    )

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Update the target project."),
        [update],
    )

    assert _unsupported(issues)["claims"] == ["Kafka"]


def _split_item() -> dict[str, Any]:
    return {
        "id": "split",
        "name": "Accessibility module",
        "role": "前端工程师",
        "techStack": ["React"],
        "period": "2024",
        "url": "",
        "description": "Reduced regression time by 30%.",
        "highlights": [],
    }


def test_split_insert_can_use_its_paired_source_item() -> None:
    source_ref = "resume:item:project:target"
    source_update = _update_target(
        {"description": "Built an accessible editor."},
        evidence_refs=[source_ref],
        edit_id="split-source",
    )
    insert = _edit(
        {
            "type": "insert_item",
            "sectionId": "project",
            "item": _split_item(),
        },
        evidence_refs=[source_ref, "prompt:current"],
        target="sections.project.items.split",
        edit_id="split-insert",
    )

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Split out an Accessibility module."),
        [source_update, insert],
    )

    assert issues == []


def test_unpaired_insert_cannot_borrow_a_sibling_item() -> None:
    insert = _edit(
        {
            "type": "insert_item",
            "sectionId": "project",
            "item": _split_item(),
        },
        evidence_refs=[
            "resume:item:project:target",
            "prompt:current",
        ],
        target="sections.project.items.split",
    )

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Add an Accessibility module."),
        [insert],
    )

    assert set(_unsupported(issues)["claims"]) >= {"30%", "React"}


@pytest.mark.parametrize("restoration_kind", ("item", "section"))
def test_exact_formal_restoration_is_allowed(restoration_kind: str) -> None:
    formal = _resume()
    active = deepcopy(formal)
    if restoration_kind == "item":
        restored = formal["sections"][0]["items"][1]
        active["sections"][0]["items"] = active["sections"][0]["items"][:1]
        operation = {
            "type": "insert_item",
            "sectionId": "project",
            "item": restored,
        }
        target = "sections.project.items.sibling"
    else:
        restored = formal["sections"][1]
        active["sections"] = active["sections"][:1]
        operation = {"type": "insert_section", "section": restored}
        target = "sections.skills"

    _, issues = ground_edit_evidence(
        active,
        _request("Restore the removed content.", resume=formal),
        [_edit(operation, target=target)],
    )

    assert issues == []


@pytest.mark.parametrize("restoration_kind", ("item", "section"))
def test_changed_formal_restoration_is_rejected(restoration_kind: str) -> None:
    formal = _resume()
    active = deepcopy(formal)
    if restoration_kind == "item":
        restored = deepcopy(formal["sections"][0]["items"][1])
        restored["description"] = "Changed restoration prose."
        active["sections"][0]["items"] = active["sections"][0]["items"][:1]
        operation = {
            "type": "insert_item",
            "sectionId": "project",
            "item": restored,
        }
        target = "sections.project.items.sibling"
    else:
        restored = deepcopy(formal["sections"][1])
        restored["title"] = "Changed title"
        active["sections"] = active["sections"][:1]
        operation = {"type": "insert_section", "section": restored}
        target = "sections.skills"

    _, issues = ground_edit_evidence(
        active,
        _request("Restore the removed content.", resume=formal),
        [_edit(operation, target=target)],
    )

    assert _unsupported(issues)["claims"] == ["restoration_content_mismatch"]


def test_user_corrections_are_not_interpreted_by_the_online_gate() -> None:
    source_id = "old-kafka-fact"
    source_ref = historical_prompt_evidence_ref(source_id)
    messages = [
        AgentConversationItem(
            id=source_id,
            role="user",
            text="I used Kafka in this project.",
        ),
        AgentConversationItem(
            id="new-correction",
            role="user",
            text="Correction: I did not use Kafka in this project.",
        ),
    ]

    _, issues = ground_edit_evidence(
        _resume(),
        _request("Rewrite the project.", messages=messages),
        [
            _update_target(
                {"techStack": ["React", "TypeScript", "Kafka"]},
                evidence_refs=["resume:item:project:target", source_ref],
            ),
        ],
    )

    assert issues == []


def test_delete_and_reorder_have_provenance_but_no_material_gate() -> None:
    edits, issues = ground_edit_evidence(
        _resume(),
        _request("Delete and reorder the projects."),
        [
            _edit(
                {
                    "type": "delete_item",
                    "sectionId": "project",
                    "itemId": "sibling",
                },
                target="sections.project.items.sibling",
                edit_id="delete",
            ),
            _edit(
                {
                    "type": "reorder_items",
                    "sectionId": "project",
                    "itemIds": ["target", "sibling"],
                },
                target="sections.project.items",
                edit_id="reorder",
            ),
        ],
    )

    assert issues == []
    assert edits[0].evidence_refs == ["resume:item:project:sibling"]
    assert edits[1].evidence_refs == ["resume:section:project"]
