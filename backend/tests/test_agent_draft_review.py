import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentChatMessage, AgentResumeEditSuggestion
from app.services.agent.draft.review import build_draft_review_items


def _edit(
    edit_id: str,
    operation: dict[str, object],
    *,
    target: str,
) -> AgentResumeEditSuggestion:
    return AgentResumeEditSuggestion(
        id=edit_id,
        title=edit_id,
        target=target,
        reason="Review grouping test.",
        operation=operation,
        status="executed",
    )


def test_section_insertion_groups_dependent_updates_and_reorder() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "insert-section",
                {
                    "type": "insert_section",
                    "section": {
                        "id": "new-section",
                        "kind": "experience",
                        "title": "Experience",
                        "items": [],
                    },
                },
                target="sections.new-section",
            ),
            _edit(
                "update-section",
                {
                    "type": "update_section",
                    "sectionId": "new-section",
                    "patch": {"title": "Selected experience"},
                },
                target="sections.new-section",
            ),
            _edit(
                "reorder-sections",
                {
                    "type": "reorder_sections",
                    "sectionIds": ["existing-section", "new-section"],
                },
                target="sections",
            ),
            _edit(
                "update-summary",
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "Focused summary",
                },
                target="basic.summary",
            ),
        ],
    )

    assert [item.id for item in review_items] == [
        "agent-review-insert-section",
        "agent-review-update-summary",
    ]
    assert review_items[0].edit_ids == [
        "insert-section",
        "update-section",
        "reorder-sections",
    ]


def test_item_insertion_groups_dependent_update_and_reorder() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "insert-item",
                {
                    "type": "insert_item",
                    "sectionId": "experience",
                    "item": {"id": "new-item", "company": "Example"},
                },
                target="sections.experience.items.new-item",
            ),
            _edit(
                "update-existing-item",
                {
                    "type": "update_item",
                    "sectionId": "experience",
                    "itemId": "existing-item",
                    "patch": {"company": "Existing"},
                },
                target="sections.experience.items.existing-item",
            ),
            _edit(
                "update-new-item",
                {
                    "type": "update_item",
                    "sectionId": "experience",
                    "itemId": "new-item",
                    "patch": {"position": "Engineer"},
                },
                target="sections.experience.items.new-item",
            ),
            _edit(
                "reorder-items",
                {
                    "type": "reorder_items",
                    "sectionId": "experience",
                    "itemIds": ["new-item", "existing-item"],
                },
                target="sections.experience.items",
            ),
        ],
    )

    assert [item.edit_ids for item in review_items] == [
        ["insert-item", "update-new-item", "reorder-items"],
        ["update-existing-item"],
    ]


def test_collection_reorder_groups_later_structural_changes() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "reorder-sections",
                {
                    "type": "reorder_sections",
                    "sectionIds": ["experience", "education"],
                },
                target="sections",
            ),
            _edit(
                "insert-section",
                {
                    "type": "insert_section",
                    "section": {
                        "id": "projects",
                        "kind": "projects",
                        "title": "Projects",
                        "items": [],
                    },
                },
                target="sections.projects",
            ),
        ],
    )

    assert [item.edit_ids for item in review_items] == [
        ["reorder-sections", "insert-section"]
    ]


def test_section_collection_structural_edits_form_one_atomic_review_item() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "insert-projects",
                {
                    "type": "insert_section",
                    "section": {
                        "id": "projects",
                        "kind": "projects",
                        "title": "Projects",
                        "items": [],
                    },
                    "index": 0,
                },
                target="sections.projects",
            ),
            _edit(
                "update-summary",
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "Focused summary",
                },
                target="basic.summary",
            ),
            _edit(
                "insert-skills",
                {
                    "type": "insert_section",
                    "section": {
                        "id": "skills",
                        "kind": "skills",
                        "title": "Skills",
                        "items": [],
                    },
                    "index": 0,
                },
                target="sections.skills",
            ),
            _edit(
                "delete-education",
                {
                    "type": "delete_section",
                    "sectionId": "education",
                },
                target="sections.education",
            ),
        ],
    )

    assert [item.edit_ids for item in review_items] == [
        ["insert-projects", "insert-skills", "delete-education"],
        ["update-summary"],
    ]


def test_item_collection_structural_edits_are_grouped_per_section() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "insert-first-role",
                {
                    "type": "insert_item",
                    "sectionId": "experience",
                    "item": {"id": "first-role", "company": "First"},
                    "index": 0,
                },
                target="sections.experience.items.first-role",
            ),
            _edit(
                "delete-education-item",
                {
                    "type": "delete_item",
                    "sectionId": "education",
                    "itemId": "old-school",
                },
                target="sections.education.items.old-school",
            ),
            _edit(
                "insert-second-role",
                {
                    "type": "insert_item",
                    "sectionId": "experience",
                    "item": {"id": "second-role", "company": "Second"},
                    "index": 0,
                },
                target="sections.experience.items.second-role",
            ),
            _edit(
                "delete-old-role",
                {
                    "type": "delete_item",
                    "sectionId": "experience",
                    "itemId": "old-role",
                },
                target="sections.experience.items.old-role",
            ),
        ],
    )

    assert [item.edit_ids for item in review_items] == [
        ["insert-first-role", "insert-second-role", "delete-old-role"],
        ["delete-education-item"],
    ]


def test_item_deletion_groups_collection_reorder() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "delete-item",
                {
                    "type": "delete_item",
                    "sectionId": "experience",
                    "itemId": "obsolete-item",
                },
                target="sections.experience.items.obsolete-item",
            ),
            _edit(
                "reorder-items",
                {
                    "type": "reorder_items",
                    "sectionId": "experience",
                    "itemIds": ["current-item"],
                },
                target="sections.experience.items",
            ),
        ],
    )

    assert [item.edit_ids for item in review_items] == [
        ["delete-item", "reorder-items"]
    ]


def test_section_deletion_groups_child_operations_and_reorder() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "update-child",
                {
                    "type": "update_item",
                    "sectionId": "obsolete-section",
                    "itemId": "child-item",
                    "patch": {"name": "Updated before deletion"},
                },
                target="sections.obsolete-section.items.child-item",
            ),
            _edit(
                "delete-section",
                {
                    "type": "delete_section",
                    "sectionId": "obsolete-section",
                },
                target="sections.obsolete-section",
            ),
            _edit(
                "reorder-sections",
                {
                    "type": "reorder_sections",
                    "sectionIds": ["experience", "education"],
                },
                target="sections",
            ),
        ],
    )

    assert [item.edit_ids for item in review_items] == [
        ["update-child", "delete-section", "reorder-sections"]
    ]


def test_repeated_writes_to_one_field_form_one_review_item() -> None:
    review_items = build_draft_review_items(
        [
            _edit(
                "summary-first",
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "First pass",
                },
                target="basic.summary",
            ),
            _edit(
                "headline",
                {
                    "type": "replace_field",
                    "path": "basic.headline",
                    "value": "Engineer",
                },
                target="basic.headline",
            ),
            _edit(
                "summary-final",
                {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "Final pass",
                },
                target="basic.summary",
            ),
        ],
    )

    assert [item.edit_ids for item in review_items] == [
        ["summary-first", "summary-final"],
        ["headline"],
    ]


def test_committed_draft_review_items_must_cover_message_edits() -> None:
    edit = _edit(
        "summary",
        {
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Focused summary",
        },
        target="basic.summary",
    )

    with pytest.raises(ValidationError) as exc_info:
        AgentChatMessage(
            id="assistant-review-coverage",
            role="assistant",
            text="Draft ready.",
            edits=[edit],
            draft={
                "baseResume": {},
                "reviewItems": [
                    {
                        "id": "agent-review-missing",
                        "editIds": ["missing"],
                        "status": "pending",
                    }
                ],
            },
            transactionState="committed",
        )

    assert exc_info.value.errors()[0]["type"] == (
        "agent_draft_review_edit_coverage_invalid"
    )


def test_committed_draft_review_items_preserve_edit_order() -> None:
    first = _edit(
        "first",
        {
            "type": "replace_field",
            "path": "basic.summary",
            "value": "First",
        },
        target="basic.summary",
    )
    second = _edit(
        "second",
        {
            "type": "replace_field",
            "path": "basic.headline",
            "value": "Second",
        },
        target="basic.headline",
    )

    with pytest.raises(ValidationError) as exc_info:
        AgentChatMessage(
            id="assistant-review-order",
            role="assistant",
            text="Draft ready.",
            edits=[first, second],
            draft={
                "baseResume": {},
                "reviewItems": [
                    {
                        "id": "agent-review-order",
                        "editIds": ["second", "first"],
                        "status": "pending",
                    }
                ],
            },
            transactionState="committed",
        )

    assert exc_info.value.errors()[0]["type"] == (
        "agent_draft_review_edit_order_invalid"
    )
