import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.draft import DraftBatchResult, DraftEditEngine


def _request(
    message_text: str = (
        "请按照 STAR 法则丰富这个项目经历，但不要编造我没有提供的个人贡献或结果。"
    ),
) -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="turn-star-feature-fragments",
            role="user",
            text=message_text,
        ),
        locale="zh",
        resume={
            "schemaVersion": 2,
            "basic": {
                "name": "示例候选人",
                "headline": "",
                "phone": "",
                "email": "",
                "location": "",
                "avatar": "",
                "summary": "",
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
                            "name": "Reseno AI Agent 简历制作网站",
                            "role": "",
                            "techStack": [
                                "React",
                                "TypeScript",
                                "Tailwind",
                                "shadcn/ui",
                            ],
                            "period": "2026.03 - 至今",
                            "url": "",
                            "description": "AI 简历制作工具。",
                            "highlights": [
                                "A4 预览",
                                "可折叠 section",
                                "实现实时编辑",
                            ],
                        },
                    ],
                },
            ],
        },
    )


def _run_highlight_edit(
    request: AgentChatRequest,
    highlights: list[str],
    *,
    evidence_refs: list[str] | None = None,
) -> tuple[DraftBatchResult, DraftEditEngine]:
    engine = DraftEditEngine.open(request)
    batch = engine.execute(
        [
            {
                "title": "丰富项目亮点",
                "target": "sections.project.items.project-1",
                "reason": "把已有事实整理为项目亮点。",
                "evidenceRefs": evidence_refs or ["resume:item:project:project-1"],
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "project-1",
                    "patch": {"highlights": highlights},
                },
            },
        ],
    )
    return batch, engine


@pytest.mark.parametrize(
    "message_text",
    [
        "请按照 STAR 法则丰富这个项目经历，但不要编造。",
        "Use the STAR method to improve my project experience.",
        "请丰富这个项目经历，但不要按 STAR 法则组织。",
    ],
)
def test_framework_shape_does_not_block_grounded_capability_edits(
    message_text: str,
) -> None:
    batch, engine = _run_highlight_edit(
        _request(message_text),
        [
            "支持 A4 预览。",
            "Section 支持折叠。",
            "支持实时编辑。",
        ],
    )
    turn = engine.finalize(completed=True)

    assert batch.accepted is True
    assert turn.transaction_state == "committed"


def test_star_rewrite_accepts_target_local_action_and_deliverable_evidence() -> None:
    request = _request(
        "候选人事实：我负责编辑器前端开发，使用 React 实现简历实时编辑，"
        "并完成 A4 预览与可折叠 Section 交付。请按照 STAR 法则丰富项目经历。",
    )
    batch, engine = _run_highlight_edit(
        request,
        [
            "负责编辑器前端开发，使用 React 实现简历实时编辑。",
            "完成 A4 预览与可折叠 Section 交付。",
        ],
        evidence_refs=[
            "resume:item:project:project-1",
            "prompt:current",
        ],
    )

    assert batch.accepted is True
    assert len(engine.edits) == 1


def test_star_request_does_not_force_framework_shape_into_the_draft() -> None:
    request = _request(
        "候选人事实：我负责编辑器前端开发，使用 React 实现简历实时编辑，"
        "并完成 A4 预览与可折叠 Section 交付。请按照 STAR 法则丰富项目经历。",
    )
    batch, _engine = _run_highlight_edit(
        request,
        ["支持 A4 预览。", "Section 支持折叠。", "支持实时编辑。"],
        evidence_refs=[
            "resume:item:project:project-1",
            "prompt:current",
        ],
    )

    assert batch.accepted is True


def test_missing_star_dimension_is_not_a_runtime_edit_gate() -> None:
    request = _request(
        "候选人事实：我负责使用 React 开发简历实时编辑功能。"
        "请按照 STAR 法则丰富项目经历。",
    )
    batch, _engine = _run_highlight_edit(
        request,
        ["负责使用 React 开发简历实时编辑功能。"],
        evidence_refs=["prompt:current"],
    )

    assert batch.accepted is True
