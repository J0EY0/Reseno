from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentChatMessage, AgentResumeEditSuggestion


def _edit() -> dict[str, object]:
    return {
        "id": "edit-summary",
        "title": "Improve summary",
        "target": "basic.summary",
        "reason": "Use the supplied description.",
        "replacement": "Updated summary",
        "status": "executed",
    }


@pytest.mark.parametrize(
    "operation", [pytest.param({}, id="absent"), {"operation": None}]
)
def test_executable_edit_requires_an_explicit_operation(
    operation: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AgentResumeEditSuggestion.model_validate({**_edit(), **operation})


def test_assistant_response_rejects_a_partial_executable_batch() -> None:
    valid_edit = {
        **_edit(),
        "operation": {
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Updated summary",
        },
    }
    with pytest.raises(ValidationError):
        AgentChatMessage.model_validate(
            {
                "id": "assistant",
                "role": "assistant",
                "text": "Review these edits.",
                "edits": [valid_edit, {**_edit(), "id": "missing-operation"}],
            }
        )


@pytest.mark.parametrize("status", ["planned", "executed", "rejected"])
def test_executable_edit_preserves_the_explicit_operation(status: str) -> None:
    operation = {
        "type": "replace_field",
        "path": "basic.summary",
        "value": "New summary",
    }
    edit = AgentResumeEditSuggestion.model_validate(
        {
            **_edit(),
            "operation": operation,
            "status": status,
        }
    )
    assert edit.operation == operation
    assert edit.status == status
    assert edit.model_dump(by_alias=True)["operation"] == operation
