from __future__ import annotations

from typing import Any

from app.schemas.agent import (
    AgentChatRequest,
    AgentResumeEditSuggestion,
)

_BASIC_FIELDS = frozenset(
    {
        "avatar",
        "email",
        "headline",
        "location",
        "name",
        "phone",
        "summary",
    },
)


def ground_edit_evidence(
    before_resume: dict[str, Any],
    request: AgentChatRequest,
    edits: list[AgentResumeEditSuggestion],
) -> tuple[list[AgentResumeEditSuggestion], list[dict[str, Any]]]:
    """Attach candidate-owned evidence to every edit and reject foreign claims.

    Public target material can explain *why* an edit is relevant, but it cannot
    prove that the candidate has an experience or result. The allowlist below
    therefore contains only the current resume, current user turn, and current
    attachments. Missing model references are inferred from the operation so
    older adapters remain compatible while response edits become traceable.
    """

    allowed_refs = _allowed_evidence_refs(before_resume, request)
    grounded_edits: list[AgentResumeEditSuggestion] = []
    issues: list[dict[str, Any]] = []

    for operation_index, edit in enumerate(edits, start=1):
        provided_refs = _unique_strings(edit.evidence_refs)
        invalid_refs = [
            reference for reference in provided_refs if reference not in allowed_refs
        ]
        if invalid_refs:
            issues.append(
                {
                    "code": "invalid_edit_evidence",
                    "severity": "error",
                    "target": edit.target,
                    "scope": "evidence",
                    "operationIndex": operation_index,
                    "invalidEvidenceRefs": invalid_refs,
                },
            )

        evidence_refs = provided_refs or _inferred_evidence_refs(
            edit.operation,
            allowed_refs,
        )
        if not evidence_refs:
            issues.append(
                {
                    "code": "missing_edit_evidence",
                    "severity": "error",
                    "target": edit.target,
                    "scope": "evidence",
                    "operationIndex": operation_index,
                },
            )

        grounded_edits.append(
            edit.model_copy(update={"evidence_refs": evidence_refs}),
        )

    return grounded_edits, issues


def _allowed_evidence_refs(
    resume: dict[str, Any],
    request: AgentChatRequest,
) -> set[str]:
    refs = {f"resume:basic:{field}" for field in _BASIC_FIELDS}
    refs.add("prompt:current")

    sections = resume.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_id = _string_value(section.get("id"))
            if not section_id:
                continue
            refs.add(f"resume:section:{section_id}")
            items = section.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = _string_value(item.get("id"))
                if item_id:
                    refs.add(f"resume:item:{section_id}:{item_id}")

    for attachment in _request_files(request):
        attachment_id = _string_value(attachment.get("id"))
        if attachment_id:
            refs.add(f"attachment:{attachment_id}")
    return refs


def _inferred_evidence_refs(
    operation: dict[str, Any] | None,
    allowed_refs: set[str],
) -> list[str]:
    if not isinstance(operation, dict):
        return []

    operation_type = _string_value(operation.get("type"))
    refs: list[str] = []
    section_id = _string_value(operation.get("sectionId"))
    item_id = _string_value(operation.get("itemId"))

    if operation_type == "replace_field":
        path = _string_value(operation.get("path"))
        if path.startswith("basic."):
            refs.append(f"resume:basic:{path.removeprefix('basic.')}")
    elif operation_type in {"update_item", "delete_item"}:
        refs.append(f"resume:item:{section_id}:{item_id}")
    elif operation_type in {
        "insert_item",
        "update_section",
        "delete_section",
        "reorder_items",
    }:
        refs.append(f"resume:section:{section_id}")
    elif operation_type == "reorder_sections":
        refs.extend(
            f"resume:section:{section_id}"
            for section_id in _string_list(operation.get("sectionIds"))
        )

    # The current turn records the user's intent and any pasted source text.
    # Attachments are allowed only when the model references one explicitly;
    # inferring every uploaded file here would claim evidence the edit may not
    # have used.
    if operation_type in {
        "insert_item",
        "insert_section",
        "replace_field",
        "update_item",
        "update_section",
    }:
        refs.append("prompt:current")

    return [
        reference for reference in _unique_strings(refs) if reference in allowed_refs
    ]


def _request_files(request: AgentChatRequest) -> list[dict[str, Any]]:
    return [file for file in request.message.files if isinstance(file, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if isinstance(item, str) and (text := item.strip())]


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
