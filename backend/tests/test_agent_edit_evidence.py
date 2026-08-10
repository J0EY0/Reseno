from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentResumeEditSuggestion,
)
from app.services.agent.evidence import ground_edit_evidence


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
