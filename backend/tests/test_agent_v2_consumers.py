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
        job_brief="",
        files=[],
        focus="languages",
    )

    assert result["candidateCount"] == 1
    assert result["candidates"][0]["suggestedSections"] == ["simple_list"]
