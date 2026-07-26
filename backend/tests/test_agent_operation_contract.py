from jsonschema import Draft7Validator

from app.services.agent.editing.operations import (
    _model_edit_suggestions_with_diagnostics,
)
from app.services.agent.operation_contract import (
    assert_model_operation_adapter_compatible,
    resume_edit_operation_error,
)
from app.services.agent.tools.registry import OPERATION_SCHEMA


def test_model_adapter_matches_canonical_operation_variants() -> None:
    assert_model_operation_adapter_compatible(OPERATION_SCHEMA)


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


def test_canonical_contract_accepts_explicit_location_replacement() -> None:
    operation = {
        "type": "replace_field",
        "path": "basic.location",
        "value": "Remote",
    }

    assert resume_edit_operation_error(operation) is None


def test_canonical_contract_rejects_frontend_only_patch_fields() -> None:
    operation = {
        "type": "update_section",
        "sectionId": "project",
        "patch": {"items": []},
    }

    assert resume_edit_operation_error(operation) is not None


def test_normalized_operations_cross_api_boundary_in_canonical_shape() -> None:
    resume = {
        "basic": {"headline": "Engineer", "summary": "Original summary"},
        "sections": [],
    }
    edits, rejected = _model_edit_suggestions_with_diagnostics(
        resume,
        [
            {
                "title": "Improve summary",
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
    assert resume_edit_operation_error(edits[0].operation) is None


def test_model_insert_section_accepts_both_documented_kind_aliases() -> None:
    validator = Draft7Validator(OPERATION_SCHEMA)

    def operation(section_kind: str, field: str) -> dict:
        return {
            "type": "insert_section",
            "section": {
                field: section_kind,
                "layout": "timeline",
                "items": [],
            },
        }

    assert validator.is_valid(operation("project", "section_type"))
    assert validator.is_valid(operation("project", "kind"))
    assert not validator.is_valid(
        {
            "type": "insert_section",
            "section": {"layout": "timeline", "items": []},
        },
    )


def test_conflicting_section_kind_aliases_reject_the_operation() -> None:
    resume = {"basic": {}, "sections": []}
    edits, rejected = _model_edit_suggestions_with_diagnostics(
        resume,
        [
            {
                "title": "Insert a contradictory section",
                "operation": {
                    "type": "insert_section",
                    "section": {
                        "section_type": "education",
                        "kind": "project",
                        "layout": "timeline",
                        "items": [],
                    },
                },
            },
        ],
        locale="en",
    )

    assert edits == []
    assert len(rejected) == 1
