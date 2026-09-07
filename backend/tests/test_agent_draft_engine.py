from copy import deepcopy
from typing import Any

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentDraftState,
)
from app.services.agent.draft import DraftEditEngine, DraftTransaction


def _basic(*, summary: str = "") -> dict:
    return {
        "name": "",
        "headline": "",
        "phone": "",
        "email": "",
        "location": "",
        "avatar": "",
        "summary": summary,
        "customFields": [],
    }


def _request(
    prompt: str,
    *,
    messages: list[AgentConversationItem] | None = None,
    files: list[dict[str, Any]] | None = None,
    resume_id: str | None = None,
) -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="turn-draft-engine",
            role="user",
            text=prompt,
            files=files or [],
        ),
        messages=messages or [],
        locale="zh",
        resumeId=resume_id,
        expectedRevision="1" if resume_id else None,
        resume={
            "schemaVersion": 2,
            "basic": _basic(summary="原始简介"),
            "sections": [
                {
                    "id": "project",
                    "kind": "project",
                    "title": "项目经历",
                    "items": [
                        {
                            "id": "untouched-project",
                            "name": "旧项目",
                            "role": "开发者",
                            "techStack": [],
                            "period": "not-a-date",
                            "url": "",
                            "description": "旧项目描述。",
                            "highlights": ["维护现有功能。"],
                        },
                        {
                            "id": "target-project",
                            "name": "Reseno",
                            "role": "后端工程师",
                            "techStack": [],
                            "period": "",
                            "url": "",
                            "description": "简历编辑器后端平台。",
                            "highlights": [
                                "A4 预览",
                                "可折叠 Section",
                                "实现实时编辑",
                            ],
                        },
                    ],
                },
            ],
        },
    )


def _edit(
    operation: dict,
    *,
    target: str,
    evidence_refs: list[str] | None = None,
) -> dict:
    entry = {
        "title": "编辑简历",
        "target": target,
        "reason": "执行用户请求。",
        "operation": operation,
    }
    if evidence_refs is not None:
        entry["evidenceRefs"] = evidence_refs
    return entry


def test_user_materials_automatically_ground_an_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.agent.evidence.attachment_text",
        lambda _resume_id, _file: "项目事实：使用 Kafka 处理消息。",
    )
    request = _request(
        "使用我之前确认的信息和当前附件优化 Reseno 项目。",
        messages=[
            AgentConversationItem(
                id="confirmed-project-result",
                role="user",
                text="补充事实：这个项目将消息吞吐提升了 45%。",
            ),
        ],
        files=[
            {
                "id": "project-notes",
                "filename": "project-notes.txt",
                "mediaType": "text/plain",
            },
        ],
        resume_id="resume1",
    )
    engine = DraftEditEngine.open(request)

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "target-project",
                    "patch": {
                        "techStack": ["Kafka"],
                        "highlights": ["将消息吞吐提升 45%。"],
                    },
                },
                target="sections.project.items.target-project",
            ),
        ],
    )

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][1] == {
        **request.resume["sections"][0]["items"][1],
        "techStack": ["Kafka"],
        "highlights": ["将消息吞吐提升 45%。"],
    }


def test_unrelated_existing_period_issue_does_not_block_summary_edit() -> None:
    engine = DraftEditEngine.open(
        _request("候选人事实：专注后端平台工程。请优化个人简介。"),
    )

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "专注后端平台工程。",
                },
                target="basic.summary",
            ),
        ],
    )

    assert batch.accepted is True
    assert batch.draft_resume["basic"]["summary"] == "专注后端平台工程。"
    assert batch.issues == ()
    assert engine.base_resume["basic"]["summary"] == "原始简介"
    assert engine.draft_resume == batch.draft_resume
    assert engine.edits == batch.edits
    assert engine.transaction_state == "provisional"

    turn = engine.finalize(completed=True)

    assert turn.transaction_state == "committed"
    assert turn.draft_resume == batch.draft_resume


def test_unrelated_existing_period_issue_does_not_block_project_highlight() -> None:
    engine = DraftEditEngine.open(
        _request(
            "候选人事实：我负责 Reseno 后端平台工程。请优化 Reseno 项目亮点。",
        ),
    )

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "target-project",
                    "patch": {"highlights": ["负责 Reseno 后端平台工程。"]},
                },
                target="sections.project.items.target-project",
                evidence_refs=[
                    "resume:item:project:target-project",
                    "prompt:current",
                ],
            ),
        ],
    )

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["period"] == "not-a-date"
    assert batch.draft_resume["sections"][0]["items"][1]["highlights"] == [
        "负责 Reseno 后端平台工程。",
    ]


def test_draft_engine_does_not_infer_permissions_from_prompt_wording() -> None:
    engine = DraftEditEngine.open(
        _request(
            "候选人事实：专注后端平台工程。不要只给建议，直接把简介改成这句话。",
        ),
    )

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "专注后端平台工程。",
                },
                target="basic.summary",
                evidence_refs=["prompt:current"],
            ),
        ],
    )
    turn = engine.finalize(completed=True)

    assert batch.accepted is True
    assert batch.draft_resume["basic"]["summary"] == "专注后端平台工程。"
    assert turn.transaction_state == "committed"


def test_field_wording_does_not_create_a_runtime_scope() -> None:
    engine = DraftEditEngine.open(
        _request("只改 Reseno 项目描述，把已有 A4 预览事实写入描述。"),
    )

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "target-project",
                    "patch": {"highlights": ["支持 A4 预览。"]},
                },
                target="sections.project.items.target-project",
                evidence_refs=["resume:item:project:target-project"],
            ),
        ],
    )

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][1]["highlights"] == [
        "支持 A4 预览。",
    ]


def test_delete_is_staged_as_a_pending_preview_without_text_routing() -> None:
    engine = DraftEditEngine.open(_request("请优化项目经历。"))

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "delete_item",
                    "sectionId": "project",
                    "itemId": "target-project",
                },
                target="sections.project.items.target-project",
            ),
        ],
    )

    assert batch.accepted is True
    assert [item["id"] for item in batch.draft_resume["sections"][0]["items"]] == [
        "untouched-project"
    ]


def test_reorder_is_staged_without_parsing_the_user_prompt() -> None:
    engine = DraftEditEngine.open(_request("请优化项目经历。"))

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "reorder_items",
                    "sectionId": "project",
                    "itemIds": ["target-project", "untouched-project"],
                },
                target="sections.project.items",
            ),
        ],
    )

    assert batch.accepted is True
    assert [item["id"] for item in batch.draft_resume["sections"][0]["items"]] == [
        "target-project",
        "untouched-project",
    ]


def test_normalization_keeps_supported_prose_that_repeats_structured_fields() -> None:
    engine = DraftEditEngine.open(
        _request(
            "候选人事实：专注后端平台工程；Reseno 项目角色是产品开发，"
            "项目描述是 Reseno 产品开发。请更新个人简介，以及 Reseno 的"
            "项目角色和项目描述。",
        ),
    )

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "专注后端平台工程。",
                },
                target="basic.summary",
            ),
            _edit(
                {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "target-project",
                    "patch": {
                        "role": "产品开发",
                        "description": "Reseno 产品开发",
                    },
                },
                target="sections.project.items.target-project",
                evidence_refs=[
                    "resume:item:project:target-project",
                    "prompt:current",
                ],
            ),
        ],
    )

    assert batch.accepted is True
    assert batch.issues == ()
    assert batch.draft_resume["basic"]["summary"] == "专注后端平台工程。"
    project = batch.draft_resume["sections"][0]["items"][1]
    assert project["role"] == "产品开发"
    assert project["description"] == "Reseno 产品开发"
    assert len(batch.edits) == 2
    assert batch.revision == 1


def test_online_style_quality_is_not_scanned() -> None:
    request = _request("只把已有的 A4 预览事实整理到项目亮点中。")
    target = request.resume["sections"][0]["items"][1]
    target["highlights"] = []
    target["description"] = "包含 A4 预览。"
    engine = DraftEditEngine.open(request)

    batch = engine.execute(
        [
            _edit(
                {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "target-project",
                    "patch": {"highlights": ["A4 预览"]},
                },
                target="sections.project.items.target-project",
                evidence_refs=["resume:item:project:target-project"],
            ),
        ],
    )

    assert batch.accepted is True
    assert batch.issues == ()
    assert batch.observation["qualityIssues"] == []


def test_pending_transaction_state_is_resolved_once_inside_draft_module() -> None:
    request = _request(
        "候选人事实：专注后端平台和分布式系统。请据此继续优化个人简介。",
    )
    saved_resume = deepcopy(request.resume)
    pending_resume = deepcopy(saved_resume)
    pending_resume["basic"]["summary"] = "专注后端平台。"
    prior_edit = {
        "id": "edit-prior-summary",
        "title": "更新简介",
        "target": "basic.summary",
        "reason": "应用上一轮请求。",
        "operation": {
            "type": "replace_field",
            "path": "basic.summary",
            "value": "专注后端平台。",
        },
        "status": "executed",
    }
    request = request.model_copy(
        update={
            "messages": [
                AgentConversationItem(
                    id="assistant-prior-draft",
                    role="assistant",
                    text="上一轮草稿。",
                    response={
                        "draft": {
                            "baseResume": saved_resume,
                            "reviewItems": [
                                {
                                    "id": "agent-review-edit-prior-summary",
                                    "editIds": ["edit-prior-summary"],
                                    "status": "pending",
                                },
                            ],
                        },
                        "edits": [prior_edit],
                        "transactionState": "committed",
                    },
                ),
            ],
            "draft_state": AgentDraftState(
                id="draft-prior",
                sourceMessageId="assistant-prior-draft",
                resume=pending_resume,
                pendingCount=1,
                reviewItems=[
                    {
                        "id": "agent-review-edit-prior-summary",
                        "editIds": ["edit-prior-summary"],
                        "status": "pending",
                    },
                ],
                edits=[
                    {
                        **prior_edit,
                        "id": "stale-client-copy-must-not-win",
                    },
                ],
            ),
        },
    )

    transaction = DraftTransaction.from_request(request)
    engine = DraftEditEngine.open(request, transaction)
    batch = engine.execute(
        [
            _edit(
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "专注后端平台和分布式系统。",
                },
                target="basic.summary",
                evidence_refs=["prompt:current"],
            ),
        ],
    )
    turn = engine.finalize(completed=True)

    assert transaction.active_resume == pending_resume
    assert transaction.base_resume == saved_resume
    assert [edit.id for edit in transaction.prior_edits] == [
        "edit-prior-summary",
    ]
    assert batch.accepted is True
    assert [edit.id for edit in engine.edits] == [
        "edit-prior-summary",
        batch.edits[0].id,
    ]
    assert turn.base_resume == saved_resume
    assert turn.draft_resume is not None
    assert turn.draft_resume["basic"]["summary"] == ("专注后端平台和分布式系统。")
