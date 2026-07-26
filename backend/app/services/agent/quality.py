import re
from typing import Any

from app.schemas.agent import AgentResumeEditSuggestion

MAX_HIGHLIGHT_CHARS = 180
MAX_SUMMARY_CHARS = 360
MAX_DESCRIPTION_CHARS = 220
MAX_ITEM_HIGHLIGHTS = 5
ITEM_TEXT_FIELDS = ("title", "subtitle", "meta", "period", "description")
ITEM_DEDUPE_FIELDS = ("title", "subtitle", "meta", "period")
BLOCKING_QUALITY_SEVERITY = "error"


def draft_quality_issues(
    after_resume: dict[str, Any],
    edits: list[AgentResumeEditSuggestion],
) -> list[dict[str, Any]]:
    """Return deterministic errors and advisory warnings from fresh edits."""

    issues: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()

    for operation_index, edit in enumerate(edits, start=1):
        operation = edit.operation or {}
        operation_type = _string_value(operation.get("type"))
        if operation_type == "replace_field":
            _add_basic_field_issues(
                issues,
                seen,
                edit,
                operation,
                operation_index,
            )
            continue

        if operation_type == "insert_section":
            section: dict[str, Any] | None = _section_by_id(
                after_resume,
                _section_id(operation.get("section")),
            )
            if section is None:
                section = _dict_value(operation.get("section"))
            if section is not None:
                _add_section_issues(
                    issues,
                    seen,
                    edit,
                    operation_type,
                    section,
                    operation_index,
                )
                for item in _section_items(section):
                    _add_item_issues(
                        issues,
                        seen,
                        edit,
                        operation_type,
                        item,
                        operation_index,
                    )
            continue

        if operation_type == "insert_item":
            inserted_item = _item_after_operation(after_resume, operation)
            if inserted_item is not None:
                _add_item_issues(
                    issues,
                    seen,
                    edit,
                    operation_type,
                    inserted_item,
                    operation_index,
                )
            continue

        if operation_type == "update_item":
            updated_item = _item_after_operation(after_resume, operation)
            if updated_item is not None:
                _add_item_issues(
                    issues,
                    seen,
                    edit,
                    operation_type,
                    updated_item,
                    operation_index,
                    touched_fields=_operation_patch_fields(operation),
                )

    return issues


def normalization_loss_issues(
    before_resume: dict[str, Any],
    entries: object,
    edits: list[AgentResumeEditSuggestion],
) -> list[dict[str, Any]]:
    """Report non-empty item content discarded while normalizing model JSON.

    Sanitization remains defensive, but silently publishing a partial operation
    would violate the Agent's atomic edit contract. Empty input still represents
    an intentional field clear and is therefore not reported.
    """

    if not isinstance(entries, list) or len(entries) != len(edits):
        return []

    issues: list[dict[str, Any]] = []
    for operation_index, (entry, edit) in enumerate(
        zip(entries, edits, strict=True),
        start=1,
    ):
        raw_operation = entry.get("operation") if isinstance(entry, dict) else None
        normalized_operation = edit.operation
        if not isinstance(raw_operation, dict) or not isinstance(
            normalized_operation,
            dict,
        ):
            continue

        operation_type = _string_value(normalized_operation.get("type"))
        if operation_type == "update_item":
            base_section = _section_by_id(
                before_resume,
                _string_value(normalized_operation.get("sectionId")),
            )
            base_item = (
                _item_by_id(
                    base_section,
                    _string_value(normalized_operation.get("itemId")),
                )
                if base_section is not None
                else None
            )
            _add_normalization_loss_for_item(
                issues,
                raw_operation.get("patch"),
                normalized_operation.get("patch"),
                edit,
                operation_type,
                operation_index,
                base_item=base_item,
            )
        elif operation_type == "insert_item":
            _add_normalization_loss_for_item(
                issues,
                raw_operation.get("item"),
                normalized_operation.get("item"),
                edit,
                operation_type,
                operation_index,
            )
        elif operation_type == "insert_section":
            raw_section = _dict_value(raw_operation.get("section"))
            normalized_section = _dict_value(normalized_operation.get("section"))
            if raw_section is None or normalized_section is None:
                continue
            raw_items = raw_section.get("items")
            normalized_items = normalized_section.get("items")
            if not isinstance(raw_items, list) or not isinstance(
                normalized_items,
                list,
            ):
                continue
            if len(raw_items) != len(normalized_items):
                issues.append(
                    {
                        "code": "normalized_section_items_were_dropped",
                        "severity": BLOCKING_QUALITY_SEVERITY,
                        "target": edit.target,
                        "operationType": operation_type,
                        "operationIndex": operation_index,
                        "field": "items",
                    },
                )
                continue
            for raw_item, normalized_item in zip(
                raw_items,
                normalized_items,
                strict=True,
            ):
                _add_normalization_loss_for_item(
                    issues,
                    raw_item,
                    normalized_item,
                    edit,
                    operation_type,
                    operation_index,
                )

    return issues


def blocking_quality_issues(
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deterministic issues that must reject the complete edit batch."""

    return [
        issue for issue in issues if issue.get("severity") == BLOCKING_QUALITY_SEVERITY
    ]


def _add_basic_field_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation: dict[str, Any],
    operation_index: int,
) -> None:
    if operation.get("path") != "basic.summary":
        return

    value = _string_value(operation.get("value"))
    if len(value) <= MAX_SUMMARY_CHARS:
        return

    _append_issue(
        issues,
        seen,
        {
            "code": "long_summary",
            "severity": "warning",
            "target": edit.target,
            "operationType": "replace_field",
            "operationIndex": operation_index,
            "field": "summary",
            "length": len(value),
            "maxLength": MAX_SUMMARY_CHARS,
        },
    )


def _add_section_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation_type: str,
    section: dict[str, Any],
    operation_index: int,
) -> None:
    if _section_has_visible_content(section):
        return

    _append_issue(
        issues,
        seen,
        {
            "code": "empty_resume_section",
            "severity": BLOCKING_QUALITY_SEVERITY,
            "target": edit.target,
            "operationType": operation_type,
            "operationIndex": operation_index,
            "scope": "section",
        },
    )


def _add_item_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation_type: str,
    item: dict[str, Any],
    operation_index: int,
    touched_fields: set[str] | None = None,
) -> None:
    if not _item_has_visible_content(item):
        _append_issue(
            issues,
            seen,
            {
                "code": "empty_resume_item",
                "severity": BLOCKING_QUALITY_SEVERITY,
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
                "scope": "item",
            },
        )

    field_values = [_string_value(item.get(field)) for field in ITEM_DEDUPE_FIELDS]
    description = _string_value(item.get("description"))
    check_description = _should_check_field(touched_fields, "description")
    if check_description and len(description) > MAX_DESCRIPTION_CHARS:
        _append_issue(
            issues,
            seen,
            {
                "code": "long_description",
                "severity": "warning",
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
                "field": "description",
                "length": len(description),
                "maxLength": MAX_DESCRIPTION_CHARS,
            },
        )
    if (
        check_description
        and description
        and _has_repeated_field_values(description, field_values)
    ):
        _append_issue(
            issues,
            seen,
            {
                "code": "duplicate_item_field_in_description",
                "severity": BLOCKING_QUALITY_SEVERITY,
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
                "field": "description",
            },
        )

    highlights = _item_highlights(item)
    check_highlights = _should_check_field(touched_fields, "highlights")
    if check_highlights and len(highlights) > MAX_ITEM_HIGHLIGHTS:
        _append_issue(
            issues,
            seen,
            {
                "code": "too_many_highlights",
                "severity": "warning",
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
                "field": "highlights",
                "count": len(highlights),
                "maxCount": MAX_ITEM_HIGHLIGHTS,
            },
        )

    if not check_highlights:
        return

    highlight_keys: dict[str, int] = {}
    for index, highlight in enumerate(highlights):
        highlight_key = _duplicate_key(highlight)
        previous_index = highlight_keys.get(highlight_key)
        if highlight_key and previous_index is not None:
            _append_issue(
                issues,
                seen,
                {
                    "code": "duplicate_highlight",
                    "severity": BLOCKING_QUALITY_SEVERITY,
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
                    "field": "highlights",
                    "index": index,
                    "duplicateOf": previous_index,
                },
            )
        else:
            highlight_keys[highlight_key] = index

        if len(highlight) > MAX_HIGHLIGHT_CHARS:
            _append_issue(
                issues,
                seen,
                {
                    "code": "long_highlight",
                    "severity": "warning",
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
                    "field": "highlights",
                    "index": index,
                    "length": len(highlight),
                    "maxLength": MAX_HIGHLIGHT_CHARS,
                },
            )
        if _has_repeated_field_values(highlight, field_values):
            _append_issue(
                issues,
                seen,
                {
                    "code": "duplicate_item_field_in_highlight",
                    "severity": BLOCKING_QUALITY_SEVERITY,
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
                    "field": "highlights",
                    "index": index,
                },
            )


def _operation_patch_fields(operation: dict[str, Any]) -> set[str]:
    patch = operation.get("patch")
    if not isinstance(patch, dict):
        return set()

    return {key for key in patch if isinstance(key, str)}


def _should_check_field(touched_fields: set[str] | None, field: str) -> bool:
    return touched_fields is None or field in touched_fields


def _add_normalization_loss_for_item(
    issues: list[dict[str, Any]],
    raw_value: object,
    normalized_value: object,
    edit: AgentResumeEditSuggestion,
    operation_type: str,
    operation_index: int,
    *,
    base_item: dict[str, Any] | None = None,
) -> None:
    raw_item = _dict_value(raw_value)
    normalized_item = _dict_value(normalized_value)
    if raw_item is None or normalized_item is None:
        return

    for field in ITEM_TEXT_FIELDS:
        raw_text = _string_value(raw_item.get(field))
        normalized_text = _string_value(normalized_item.get(field))
        if (
            raw_text
            and not normalized_text
            and not _same_text(raw_text, _string_value((base_item or {}).get(field)))
        ):
            issues.append(
                {
                    "code": "normalized_item_field_was_dropped",
                    "severity": BLOCKING_QUALITY_SEVERITY,
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
                    "field": field,
                },
            )

    raw_highlights = _string_list(raw_item.get("highlights"))
    normalized_highlights = _string_list(normalized_item.get("highlights"))
    base_highlights = _string_list((base_item or {}).get("highlights"))
    if (
        raw_highlights
        and len(normalized_highlights) < len(raw_highlights)
        and not _same_string_list(raw_highlights, base_highlights)
    ):
        issues.append(
            {
                "code": "normalized_item_highlights_were_dropped",
                "severity": BLOCKING_QUALITY_SEVERITY,
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
                "field": "highlights",
            },
        )


def _append_issue(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    issue: dict[str, Any],
) -> None:
    key = (
        issue.get("code"),
        issue.get("target"),
        issue.get("operationIndex"),
        issue.get("field"),
        issue.get("index"),
    )
    if key in seen:
        return

    seen.add(key)
    issues.append(issue)


def _item_after_operation(
    resume: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any] | None:
    section = _section_by_id(resume, _string_value(operation.get("sectionId")))
    if section is None:
        return None

    operation_type = _string_value(operation.get("type"))
    if operation_type == "insert_item":
        item_id = _item_id(operation.get("item"))
    else:
        item_id = _string_value(operation.get("itemId"))

    return _item_by_id(section, item_id)


def _section_by_id(
    resume: dict[str, Any],
    section_id: str,
) -> dict[str, Any] | None:
    if not section_id:
        return None

    for section in _resume_sections(resume):
        if section.get("id") == section_id:
            return section

    return None


def _item_by_id(
    section: dict[str, Any],
    item_id: str,
) -> dict[str, Any] | None:
    if not item_id:
        return None

    for item in _section_items(section):
        if item.get("id") == item_id:
            return item

    return None


def _resume_sections(resume: dict[str, Any]) -> list[dict[str, Any]]:
    sections = resume.get("sections")
    if not isinstance(sections, list):
        return []

    return [section for section in sections if isinstance(section, dict)]


def _section_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    items = section.get("items")
    if not isinstance(items, list):
        return []

    return [item for item in items if isinstance(item, dict)]


def _section_has_visible_content(section: dict[str, Any]) -> bool:
    if _string_value(section.get("customTitle")):
        return True

    return any(_item_has_visible_content(item) for item in _section_items(section))


def _item_has_visible_content(item: dict[str, Any]) -> bool:
    for field in ITEM_TEXT_FIELDS:
        if _string_value(item.get(field)):
            return True

    return bool(_item_highlights(item))


def _item_highlights(item: dict[str, Any]) -> list[str]:
    highlights = item.get("highlights")
    if not isinstance(highlights, list):
        return []

    values = [_string_value(highlight) for highlight in highlights]
    return [highlight for highlight in values if highlight]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    return [text for item in value if (text := _string_value(item))]


def _section_id(value: object) -> str:
    data = _dict_value(value)
    return _string_value(data.get("id")) if data is not None else ""


def _item_id(value: object) -> str:
    data = _dict_value(value)
    return _string_value(data.get("id")) if data is not None else ""


def _dict_value(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _duplicate_key(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())


def _same_text(first: str, second: str) -> bool:
    return bool(first and second) and _duplicate_key(first) == _duplicate_key(second)


def _same_string_list(first: list[str], second: list[str]) -> bool:
    return [_duplicate_key(value) for value in first] == [
        _duplicate_key(value) for value in second
    ]


def _has_repeated_field_values(value: str, field_values: list[str]) -> bool:
    value_key = _duplicate_key(value)
    field_keys = {
        field_key
        for field_value in field_values
        if len(field_key := _duplicate_key(field_value)) >= 3
    }
    return sum(field_key in value_key for field_key in field_keys) >= 2
