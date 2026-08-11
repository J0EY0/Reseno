from copy import deepcopy

from app.services.agent.editing.operations import (
    _apply_edit_operation,
    _model_edit_suggestions_with_diagnostics,
)
from app.services.agent.materials import extract_resume_materials
from app.services.agent.runtime.messages import _compact_resume_outline
from app.services.agent.tools.structured import (
    classify_skills_entries,
    lookup_resume,
    move_item_entries,
)


def test_resume_lookup_returns_kind_specific_item_fields() -> None:
    resume = {
        "sections": [
            {
                "id": "projects",
                "kind": "project",
                "title": "Projects",
                "items": [
                    {
                        "id": "project-1",
                        "name": "ResuMate",
                        "role": "Developer",
                        "techStack": ["React", "FastAPI"],
                        "period": "2026",
                        "url": "",
                        "description": "AI resume editor.",
                        "highlights": [],
                    },
                ],
            },
        ],
    }

    result = lookup_resume(resume, {"query": "FastAPI"})

    assert result["itemCount"] == 1
    assert result["items"][0] == {
        "sectionId": "projects",
        "sectionKind": "project",
        "id": "project-1",
        "name": "ResuMate",
        "role": "Developer",
        "period": "2026",
        "description": "AI resume editor.",
        "techStack": ["React", "FastAPI"],
    }


def test_skills_classify_builds_one_rich_text_simple_list_item() -> None:
    entries, error = classify_skills_entries(
        {"sections": []},
        {
            "groups": [
                {"title": "Frontend", "skills": ["React", "TypeScript"]},
                {"title": "Backend", "skills": ["Python"]},
            ],
        },
        locale="en",
    )

    assert error is None
    section = entries[0]["operation"]["section"]
    assert section["kind"] == "simple_list"
    assert section["title"] == "Skills"
    assert len(section["items"]) == 1
    assert [item["content"] for item in section["items"]] == [
        "<ul><li>Frontend: React, TypeScript</li><li>Backend: Python</li></ul>",
    ]


def test_skills_classify_rejects_unregistered_highlights_alias() -> None:
    entries, error = classify_skills_entries(
        {"sections": []},
        {"groups": [{"title": "Frontend", "highlights": ["React"]}]},
        locale="en",
    )

    assert entries == []
    assert error is not None


def test_move_item_rejects_simple_list_structure_changes() -> None:
    resume = {
        "sections": [
            {
                "id": "projects",
                "kind": "project",
                "title": "Projects",
                "items": [{"id": "project-1", "name": "ResuMate"}],
            },
            {
                "id": "other",
                "kind": "simple_list",
                "title": "Other",
                "items": [{"id": "other-1", "content": "React"}],
            },
        ],
    }

    entries, error = move_item_entries(
        resume,
        {
            "fromSectionId": "projects",
            "toSectionId": "other",
            "itemId": "project-1",
        },
        locale="en",
    )

    assert entries == []
    assert error == (
        "simple_list has one rich-text content item; update its content instead."
    )


def test_move_item_between_same_kind_sections_is_one_valid_batch() -> None:
    item = {
        "id": "project-1",
        "name": "ResuMate",
        "role": "Frontend engineer",
        "techStack": ["React"],
        "period": "2026",
        "url": "",
        "description": "AI resume editor.",
        "highlights": ["Built draft review."],
    }
    resume = {
        "schemaVersion": 2,
        "basic": {
            "name": "",
            "headline": "Engineer",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "",
            "customFields": [],
        },
        "sections": [
            {
                "id": "projects-current",
                "kind": "project",
                "title": "Current projects",
                "items": [item],
            },
            {
                "id": "projects-selected",
                "kind": "project",
                "title": "Selected projects",
                "items": [],
            },
        ],
    }
    entries, error = move_item_entries(
        resume,
        {
            "fromSectionId": "projects-current",
            "toSectionId": "projects-selected",
            "itemId": "project-1",
        },
        locale="en",
    )
    candidate = deepcopy(resume)

    edits, rejected = _model_edit_suggestions_with_diagnostics(
        candidate,
        entries,
        locale="en",
    )

    assert error is None
    assert rejected == []
    assert len(edits) == 2
    for edit in edits:
        assert edit.operation is not None
        _apply_edit_operation(candidate, edit.operation)
    assert candidate["sections"][0]["items"] == []
    assert candidate["sections"][1]["items"] == [item]


def test_compact_resume_outline_uses_canonical_names() -> None:
    outline = _compact_resume_outline(
        {
            "schemaVersion": 2,
            "basic": {"headline": "Engineer", "summary": ""},
            "sections": [
                {
                    "id": "achievements",
                    "kind": "achievement",
                    "title": "Certificates & Honors",
                    "items": [
                        {
                            "id": "achievement-1",
                            "name": "AWS Certified Developer",
                            "issuer": "AWS",
                            "date": "2026-05",
                        },
                    ],
                },
            ],
        },
    )

    assert outline["schemaVersion"] == 2
    assert outline["sections"][0]["items"] == [
        {
            "id": "achievement-1",
            "name": "AWS Certified Developer",
            "issuer": "AWS",
            "date": "2026-05",
        },
    ]


def test_language_materials_suggest_canonical_simple_list_section() -> None:
    result = extract_resume_materials(
        session_id="",
        prompt="语言能力：英语 CET-6 600 分，能够熟练阅读技术文档。",
        target_context="",
        files=[],
        focus="languages",
    )

    assert result["candidateCount"] == 1
    assert result["candidates"][0]["suggestedSections"] == ["simple_list"]
