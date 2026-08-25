from copy import deepcopy

import pytest

from app.services.agent.contracts import resume_edit_operation_error
from app.services.agent.editing.operations import (
    _apply_edit_operation,
    parse_edit_batch,
)
from app.services.resume_document_contract import (
    RESUME_DOCUMENT_DUPLICATE_ID,
    RESUME_DOCUMENT_INVALID,
    ResumeDocumentContractError,
    validate_resume_document,
)


def _basic() -> dict:
    return {
        "name": "",
        "headline": "",
        "phone": "",
        "email": "",
        "location": "",
        "avatar": "",
        "summary": "",
        "customFields": [],
    }


def _resume() -> dict:
    return {
        "schemaVersion": 2,
        "basic": _basic(),
        "sections": [
            {
                "id": "education",
                "kind": "education",
                "title": "Education",
                "items": [
                    {
                        "id": "education-1",
                        "school": "Zhejiang University",
                        "degree": "Bachelor",
                        "major": "Computer Science",
                        "gpa": "3.8 / 4.0",
                        "location": "Hangzhou",
                        "period": "2019 - 2023",
                        "description": "",
                        "highlights": ["First-class scholarship"],
                    }
                ],
            },
            {
                "id": "experience",
                "kind": "experience",
                "title": "Experience",
                "items": [
                    {
                        "id": "experience-1",
                        "company": "Acme",
                        "position": "Frontend Engineer",
                        "location": "Remote",
                        "period": "2023 - Present",
                        "description": "Product engineering.",
                        "highlights": ["Improved startup time by 40%."],
                    }
                ],
            },
            {
                "id": "project",
                "kind": "project",
                "title": "Projects",
                "items": [
                    {
                        "id": "project-1",
                        "name": "ResuMate",
                        "role": "Maintainer",
                        "techStack": ["React", "FastAPI"],
                        "period": "2026",
                        "url": "https://example.com/resumate",
                        "description": "Resume builder.",
                        "highlights": ["Implemented typed sections."],
                    }
                ],
            },
            {
                "id": "achievement",
                "kind": "achievement",
                "title": "Certificates & Honors",
                "items": [
                    {
                        "id": "achievement-1",
                        "name": "Example Award",
                        "issuer": "Example Foundation",
                        "date": "2025",
                        "url": "https://example.com/award",
                        "description": "First prize.",
                    }
                ],
            },
            {
                "id": "skills",
                "kind": "simple_list",
                "title": "Skills",
                "items": [
                    {"id": "skill-1", "content": "React: proficient"},
                ],
            },
        ],
    }


def _parse_operation(resume: dict, operation: object) -> dict | None:
    edits, _rejected = parse_edit_batch(
        resume,
        [{"operation": operation}],
        locale="en",
    )
    return edits[0].operation if edits else None


def test_resume_v2_accepts_every_discriminated_section() -> None:
    resume = _resume()

    assert validate_resume_document(resume) is resume


@pytest.mark.parametrize(
    "items",
    [
        [],
        [
            {"id": "skill-1", "content": "React"},
            {"id": "skill-2", "content": "TypeScript"},
        ],
    ],
)
def test_resume_v2_requires_exactly_one_simple_list_item(items: list[dict]) -> None:
    resume = _resume()
    resume["sections"][4]["items"] = items

    with pytest.raises(ResumeDocumentContractError) as error:
        validate_resume_document(resume)

    assert error.value.code == RESUME_DOCUMENT_INVALID


@pytest.mark.parametrize(
    ("path", "unknown_key"),
    [
        ((), "legacyRoot"),
        (("basic",), "legacyBasic"),
        (("sections", 0), "layout"),
        (("sections", 0, "items", 0), "title"),
    ],
)
def test_resume_v2_rejects_unknown_fields(
    path: tuple[str | int, ...],
    unknown_key: str,
) -> None:
    resume = _resume()
    target: object = resume
    for part in path:
        target = target[part]  # type: ignore[index]
    assert isinstance(target, dict)
    target[unknown_key] = "legacy"

    with pytest.raises(ResumeDocumentContractError) as error:
        validate_resume_document(resume)

    assert error.value.code == RESUME_DOCUMENT_INVALID


def test_resume_v2_rejects_item_shape_from_another_kind() -> None:
    resume = _resume()
    resume["sections"][4]["items"] = [deepcopy(resume["sections"][2]["items"][0])]

    with pytest.raises(ResumeDocumentContractError) as error:
        validate_resume_document(resume)

    assert error.value.code == RESUME_DOCUMENT_INVALID


@pytest.mark.parametrize("duplicate", ["section", "item"])
def test_resume_v2_rejects_duplicate_document_node_ids(duplicate: str) -> None:
    resume = _resume()
    if duplicate == "section":
        resume["sections"][1]["id"] = resume["sections"][0]["id"]
    else:
        resume["sections"][1]["items"][0]["id"] = resume["sections"][0]["items"][0][
            "id"
        ]

    with pytest.raises(ResumeDocumentContractError) as error:
        validate_resume_document(resume)

    assert error.value.code == RESUME_DOCUMENT_DUPLICATE_ID


@pytest.mark.parametrize("node", ["section", "item"])
def test_resume_v2_rejects_evidence_delimiters_in_node_ids(node: str) -> None:
    resume = _resume()
    target = resume["sections"][0]
    if node == "section":
        target["id"] = "education:archive"
    else:
        target["items"][0]["id"] = "education:primary"

    with pytest.raises(ResumeDocumentContractError) as error:
        validate_resume_document(resume)

    assert error.value.code == RESUME_DOCUMENT_INVALID


def test_agent_update_item_is_scoped_to_target_section_kind() -> None:
    resume = _resume()

    accepted = _parse_operation(
        resume,
        {
            "type": "update_item",
            "sectionId": "skills",
            "itemId": "skill-1",
            "patch": {"content": "React: expert"},
        },
    )
    rejected = _parse_operation(
        resume,
        {
            "type": "update_item",
            "sectionId": "project",
            "itemId": "project-1",
            "patch": {"content": "Not a project field"},
        },
    )

    assert accepted == {
        "type": "update_item",
        "sectionId": "skills",
        "itemId": "skill-1",
        "patch": {"content": "React: expert"},
    }
    assert rejected is None
    assert resume_edit_operation_error(accepted) is None


def test_agent_insert_item_accepts_exact_canonical_target_shape() -> None:
    resume = _resume()

    operation = _parse_operation(
        resume,
        {
            "type": "insert_item",
            "sectionId": "project",
            "item": {
                "id": "project-2",
                "name": "Compiler",
                "role": "Author",
                "techStack": [],
                "period": "",
                "url": "",
                "description": "",
                "highlights": [],
            },
        },
    )

    assert operation is not None
    assert operation["item"] == {
        "id": "project-2",
        "name": "Compiler",
        "role": "Author",
        "techStack": [],
        "period": "",
        "url": "",
        "description": "",
        "highlights": [],
    }
    assert resume_edit_operation_error(operation) is None

    _apply_edit_operation(resume, operation)
    assert validate_resume_document(resume) is resume


@pytest.mark.parametrize(
    "operation",
    [
        {
            "type": "insert_item",
            "sectionId": "skills",
            "item": {"id": "skill-2", "content": "TypeScript"},
        },
        {
            "type": "delete_item",
            "sectionId": "skills",
            "itemId": "skill-1",
        },
        {
            "type": "reorder_items",
            "sectionId": "skills",
            "itemIds": ["skill-1"],
        },
    ],
)
def test_agent_rejects_simple_list_item_cardinality_changes(
    operation: dict,
) -> None:
    resume = _resume()
    before = deepcopy(resume)

    assert _parse_operation(resume, operation) is None
    assert resume == before


def test_agent_rejects_wrong_kind_insert_and_raw_kind_patch() -> None:
    resume = _resume()

    wrong_item = _parse_operation(
        resume,
        {
            "type": "insert_item",
            "sectionId": "project",
            "item": {"id": "project-2", "content": "React: expert"},
        },
    )
    raw_kind_change = _parse_operation(
        resume,
        {
            "type": "update_section",
            "sectionId": "project",
            "patch": {"kind": "simple_list"},
        },
    )

    assert wrong_item is None
    assert raw_kind_change is None


def test_agent_can_only_patch_section_title() -> None:
    resume = _resume()

    operation = _parse_operation(
        resume,
        {
            "type": "update_section",
            "sectionId": "project",
            "patch": {"title": "Selected Projects"},
        },
    )

    assert operation == {
        "type": "update_section",
        "sectionId": "project",
        "patch": {"title": "Selected Projects"},
    }
    assert resume_edit_operation_error(operation) is None
