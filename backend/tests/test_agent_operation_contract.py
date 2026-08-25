from jsonschema import Draft7Validator

from app.services.agent.contracts import (
    OPERATION_SCHEMA,
    resume_edit_operation_error,
)
from app.services.agent.editing.operations import (
    parse_edit_batch,
)


def _resume_with_project() -> dict:
    return {
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
                "id": "project",
                "kind": "project",
                "title": "Projects",
                "items": [],
            },
        ],
    }


def test_canonical_contract_accepts_normalized_operation() -> None:
    operation = {
        "type": "update_item",
        "sectionId": "project",
        "itemId": "project-1",
        "patch": {
            "description": "Built a resumable import pipeline.",
            "highlights": ["Reduced recovery time by 40%."],
        },
    }

    assert resume_edit_operation_error(operation) is None


def test_canonical_contract_rejects_evidence_delimiters_in_selectors() -> None:
    operation = {
        "type": "update_item",
        "sectionId": "project:archive",
        "itemId": "project:primary",
        "patch": {"description": "Updated description."},
    }

    assert resume_edit_operation_error(operation) is not None


def test_canonical_contract_rejects_hidden_location_replacement() -> None:
    operation = {
        "type": "replace_field",
        "path": "basic.location",
        "value": "Remote",
    }

    assert resume_edit_operation_error(operation) is not None


def test_canonical_contract_rejects_frontend_only_patch_fields() -> None:
    operation = {
        "type": "update_section",
        "sectionId": "project",
        "patch": {"items": []},
    }

    assert resume_edit_operation_error(operation) is not None


def test_canonical_contract_requires_one_simple_list_item() -> None:
    def operation(items: list[dict[str, str]]) -> dict:
        return {
            "type": "insert_section",
            "section": {
                "id": "skills",
                "kind": "simple_list",
                "title": "Skills",
                "items": items,
            },
        }

    assert (
        resume_edit_operation_error(
            operation([{"id": "skill-1", "content": "React"}]),
        )
        is None
    )
    assert resume_edit_operation_error(operation([])) is not None
    assert (
        resume_edit_operation_error(
            operation(
                [
                    {"id": "skill-1", "content": "React"},
                    {"id": "skill-2", "content": "TypeScript"},
                ],
            ),
        )
        is not None
    )


def test_normalized_operations_cross_api_boundary_in_canonical_shape() -> None:
    resume = {
        "schemaVersion": 2,
        "basic": {
            "name": "",
            "headline": "Engineer",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "Original summary",
            "customFields": [],
        },
        "sections": [],
    }
    edits, rejected = parse_edit_batch(
        resume,
        [
            {
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "Outcome-focused engineer.",
                },
            },
        ],
        locale="en",
    )

    assert rejected == []
    assert len(edits) == 1
    assert edits[0].title == "Update Summary"
    assert edits[0].target == "basic.summary"
    assert resume_edit_operation_error(edits[0].operation) is None


def test_model_insert_section_accepts_compact_canonical_fields() -> None:
    validator = Draft7Validator(OPERATION_SCHEMA)
    compact = {
        "type": "insert_section",
        "section": {
            "id": "projects",
            "kind": "project",
        },
    }
    compatibility_alias = {
        "type": "insert_section",
        "section": {
            "id": "projects",
            "section_type": "project",
            "title": "Projects",
            "items": [],
        },
    }

    assert validator.is_valid(compact)
    assert not validator.is_valid(compatibility_alias)

    edits, rejected = parse_edit_batch(
        {**_resume_with_project(), "sections": []},
        [{"operation": compact}],
        locale="en",
    )
    assert rejected == []
    assert edits[0].title == "Add Project"
    assert edits[0].operation is not None
    assert edits[0].operation["section"]["title"] == ""
    assert edits[0].operation["section"]["items"] == []
    assert resume_edit_operation_error(edits[0].operation) is None


def test_insert_item_still_requires_an_id() -> None:
    resume = _resume_with_project()
    incomplete_operation = {
        "type": "insert_item",
        "sectionId": "project",
        "item": {
            "name": "ResuMate",
            "highlights": ["Built a resume editor."],
        },
    }

    edits, rejected = parse_edit_batch(
        resume,
        [{"operation": incomplete_operation}],
        locale="en",
    )

    assert resume_edit_operation_error(incomplete_operation) is not None
    assert edits == []
    assert len(rejected) == 1
    assert "Canonical protocol error" in rejected[0]["reason"]


def test_compact_project_insert_is_normalized_to_the_frontend_contract() -> None:
    operation = {
        "type": "insert_item",
        "sectionId": "project",
        "item": {
            "id": "project-2",
            "name": "Course schedule",
            "role": "Frontend developer",
            "techStack": ["React", "TypeScript"],
            "period": "2025.03 - 2025.05",
            "description": "Built course schedule creation and filtering.",
            "highlights": ["Created and edited schedules", "Filtered schedules"],
        },
    }

    assert resume_edit_operation_error(operation) == (
        "item: 'url' is a required property"
    )
    assert Draft7Validator(OPERATION_SCHEMA).is_valid(operation)

    edits, rejected = parse_edit_batch(
        _resume_with_project(),
        [{"operation": operation}],
        locale="en",
    )

    assert rejected == []
    assert edits[0].operation is not None
    assert edits[0].operation["item"]["url"] == ""
    assert resume_edit_operation_error(edits[0].operation) is None
